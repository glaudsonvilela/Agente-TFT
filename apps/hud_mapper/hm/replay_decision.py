"""Patch-bound replay state and conservative first purchase decision.

Geometry, OCR and patch metadata are independent. A readable shop name is
bound to the catalog only when it has one exact match. An upgrade instruction
also requires verified owned unit identities from the board/bench observer.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import math
import re
from pathlib import Path
import unicodedata
from .economy_budget import EconomyBudget
from .strategic_coach import StrategicCoach
from .shop_name_evidence import readable_name
from .live_advice import LiveAdvice


def _key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.strip()).casefold()
    return "".join(char for char in folded if not unicodedata.combining(char))


def _gold(answer: dict) -> int | None:
    rows = [row for row in answer.get("hud") or []
            if row.get("field") == "gold" and
            row.get("status") == "single_frame_observation" and
            type(row.get("value")) is int and
            float(row.get("confidence") or 0) >= .85]
    return rows[0]["value"] if len(rows) == 1 and 0 <= rows[0]["value"] <= 300 else None


class ReplayDecisionEngine:
    def __init__(self, configs: str, preference_path=None):
        root = Path(configs).resolve().parent
        catalog = json.loads((root / "configs/catalog/active-visual-reference-v1.json").read_text(encoding="utf-8"))
        context = json.loads((root / "configs/contexts/match001-interface.json").read_text(encoding="utf-8"))
        if catalog["set_key"] != context["set_key"]:
            raise ValueError("Patch and visual catalog refer to different sets")
        reference = root / catalog["reference"]
        manifest = json.loads((reference / "reference.json").read_text(encoding="utf-8"))
        champions = json.loads((reference / "champions.json").read_text(encoding="utf-8"))
        if (manifest["set_key"] != catalog["set_key"] or
                champions["set_key"] != catalog["set_key"] or
                champions["version"] != manifest["version"]):
            raise ValueError("Champion catalog and patch reference differ")
        self.patch = context["tft_patch"]
        self.set_key = catalog["set_key"]
        self.catalog_version = manifest["version"]
        knowledge = json.loads((root / "configs/catalog/active-knowledge-release-v1.json").read_text(encoding="utf-8"))
        release = root / knowledge["reference"]
        release_manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
        units_bytes = (release / "units.json").read_bytes()
        traits_bytes = (release / "traits.json").read_bytes()
        if (knowledge["set_key"] != self.set_key or knowledge["tft_patch"] != self.patch or
                release_manifest["set"]["key"] != self.set_key or
                release_manifest["tft_patch"] != self.patch or
                release_manifest["components"]["units"]["sha256"] != hashlib.sha256(units_bytes).hexdigest() or
                release_manifest["components"]["traits"]["sha256"] != hashlib.sha256(traits_bytes).hexdigest()):
            raise ValueError("Champion attributes and selected patch differ")
        units = json.loads(units_bytes)["champions"]
        traits = json.loads(traits_bytes)["traits"]
        trait_breakpoints = {trait['name']: sorted({effect['min_units']
            for effect in trait.get('effects') or []
            if type(effect.get('min_units')) is int and effect['min_units'] >= 2})
            for trait in traits}
        self.champion_attributes = {unit["api_name"]: unit for unit in units}
        if set(self.champion_attributes) != {entry["id"] for entry in champions["entries"]}:
            raise ValueError("Champion attributes and visual identities differ")
        self.knowledge_release = release_manifest["release_sha256"]
        names = {}
        for entry in champions["entries"]:
            names.setdefault(_key(entry["name"]), set()).add(entry["id"])
        self.names = names
        self.economy_policy = json.loads((root / "configs/contexts/replay-economy-policy-v1.json").read_text())
        if (self.economy_policy['set_key'], self.economy_policy['tft_patch']) != (self.set_key, self.patch):
            raise ValueError("Economy policy belongs to another patch")
        self._economy_previous = None
        self.resource_engine = EconomyBudget(root, patch=self.patch, set_key=self.set_key)
        self.strategic_coach = StrategicCoach(root)
        if (self.strategic_coach.catalog['patch'], self.strategic_coach.catalog['set_key'],
                self.strategic_coach.catalog['release_sha256']) != (self.patch, self.set_key, self.knowledge_release):
            raise ValueError('Strategic coach and observed catalog context differ')
        self.live_advice = LiveAdvice(economy=self.resource_engine,
            windows=self.economy_policy['level_windows'],
            champions=self.champion_attributes, trait_breakpoints=trait_breakpoints,
            preference_path=preference_path)

    def _fallback_decision(self, output, reason, visual_candidates=None):
        if hasattr(self.live_advice, 'propose_all'):
            provisional = self.live_advice.propose_all(output, visual_candidates)
        else:
            proposal = self.live_advice.propose(output, visual_candidates)
            provisional = [proposal] if proposal else []
        economy = self._economy(output)
        choices = list(provisional)
        if economy and economy.get('action', {}).get('type') != 'wait':
            kind = economy['action']['type']
            score = {'buy_xp': .84, 'hold_econ': .38}.get(kind, .55)
            choices.append({**economy, 'rank_score': score,
                            'rank_source': 'verified_economy_priority_v1'})
        for candidate in choices:
            kind = candidate.get('action', {}).get('type')
            # A fresh, concrete purchase beats a long-horizon XP reminder.
            if kind == 'buy_synergy':
                candidate['rank_score'] = max(.91, candidate.get('rank_score', 0))
            elif kind == 'buy_pair':
                candidate['rank_score'] = max(.88, candidate.get('rank_score', 0))
        choices.sort(key=lambda row: row.get('rank_score', 0), reverse=True)
        # These are visual interpretations, not final decisions. The resident
        # Rust worker selects among them before anything is spoken.
        output['decision_options'] = copy.deepcopy(choices)
        output['decision_candidates'] = [dict(action=row['action'],
            rank_score=row.get('rank_score'), rank_source=row.get('rank_source'),
            decision_key=row.get('decision_key'), basis=row.get('basis')) for row in choices]
        return choices[0] if choices else economy or self._economy_wait(reason)

    @staticmethod
    def rank_with_native(output, worker):
        """Ask the Rust motor to select an observed option; abstain on failure."""
        choices = output.pop('decision_options', None)
        if choices is None:
            return output
        if not choices:
            return output
        gold = _gold(output)
        hp_row = output.get('hp') or {}
        hp_delivery = output.get('hp_delivery') or {}
        hp = (hp_row.get('hp') if hp_row.get('status') == 'accepted'
              and hp_delivery.get('fresh') is True else None)
        context = {'gold': gold, 'hp': hp}
        try:
            result = worker.request(dict(op='rank_advice', id=output['id'],
                source_ms=output['source_ms'], candidates=choices[:24],
                context=context), timeout=2)
            index = result.get('selected_index')
            if (result.get('origin') != 'rust_live_opportunity_v1'
                    or type(index) is not int or not 0 <= index < min(24, len(choices))):
                raise ValueError('native motor abstained')
        except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
            output['decision'] = ReplayDecisionEngine._wait('RUST_MOTOR_UNAVAILABLE')
            output['decision_rank'] = {'status': 'abstained', 'reason': str(exc)}
            return output
        output['decision'] = choices[index]
        output['decision']['calculation_source'] = 'rust_live_opportunity_v1'
        output['decision_rank'] = dict(status='selected', selected_index=index,
            ranked=result.get('ranked') or [], native_ms=result.get('native_ms'))
        return output

    def evaluate(self, answer: dict, owned: dict | None = None, strategy_state: dict | None = None,
                 visual_candidates: dict | None = None) -> dict:
        """Return a new answer; never turn a candidate icon into a owned unit."""
        output = copy.deepcopy(answer)
        output["decision_capabilities"] = dict(level="conditional_economy", buy="fresh_shop_with_partial_context",
                                                roll="verified_state_required", composition="verified_state_required",
                                                position="verified_state_required", equip="verified_state_required")
        output["decision_capabilities"].update(
            resource_engine="resource_budget_v1", scope="economy_only",
            learned_policy=False, abilities_used=False)
        shop = output.get("shop") or {}
        bound = 0
        for slot in shop.get("slots") or []:
            name = slot.get("observed_name")
            if (slot.get("status") not in ("offer_text_readable", "partially_readable") or
                    not readable_name(slot)):
                continue
            matches = self.names.get(_key(name), set())
            if len(matches) == 1:
                slot["unit_id"] = next(iter(matches))
                slot["catalog_status"] = "unique_name_bound"
                slot["catalog_set"] = self.set_key
                slot["catalog_version"] = self.catalog_version
                bound += 1
            elif matches:
                slot["catalog_status"] = "ambiguous_name"
            else:
                slot["catalog_status"] = "name_not_in_patch"
        output["catalog_binding"] = {
            "patch": self.patch, "set_key": self.set_key,
            "data_dragon_version": self.catalog_version,
            "knowledge_release": self.knowledge_release,
            "basis": "reported_replay_patch_and_unique_ocr_name",
            "bound_offers": bound}
        strategy = self.strategic_coach.evaluate(strategy_state)
        observed_gold = _gold(output)
        if strategy_state and observed_gold is not None and observed_gold != strategy_state.get('gold'):
            strategy['recommendations'] = []
            strategy['blockers'] = ['BOARD_RESOURCE_FRAME_MISMATCH']
        output["strategic_coaching"] = strategy
        output['decision_capabilities'].update(strategic_scope=strategy['scope'],
            learned_ranker_loaded=strategy['learned_ranker'],
            structured_state_accepted=bool(strategy.get('candidates_evaluated')
                and 'BOARD_RESOURCE_FRAME_MISMATCH' not in strategy['blockers']))
        if strategy["recommendations"]:
            output['decision_capabilities'].update(scope=strategy['scope'],
                learned_policy=strategy['learned_ranker'])
            chosen = strategy["recommendations"][0]
            output["decision"] = dict(action=chosen["action"], text=chosen["text"],
                policy="attribute_coach_v1", confidence=.9,
                confidence_basis="verified_inputs_not_action_success", scope=strategy["scope"],
                learned_ranker=strategy["learned_ranker"],
                evidence=[dict(code="OBSERVED_ATTRIBUTE_ALTERNATIVE", detail=chosen["evidence_id"])])
            return output
        # The present B4 observer is candidate-only. Its rows cannot establish
        # a roster; a future validated observer must pass this explicit shape.
        verified = ((owned or {}).get("verified") is True and
                    (owned or {}).get("perspective") == "self")
        units = (owned or {}).get("units") or []
        if not verified or not units:
            output["decision"] = self._fallback_decision(output, "OWNED_UNITS_UNVERIFIED", visual_candidates)
            return output
        age_ms = owned.get("age_ms")
        if type(age_ms) not in (int, float) or not 0 <= age_ms <= 2000:
            output["decision"] = self._wait("OWNED_UNITS_STALE")
            return output
        copies = Counter()
        for unit in units:
            if (unit.get("identity_verified") is True and
                    isinstance(unit.get("unit_id"), str) and
                    unit.get("stars") == 1):
                copies[unit["unit_id"]] += 1
        gold = _gold(output)
        if gold is None:
            output["decision"] = self._wait("GOLD_UNVERIFIED")
            return output
        if not self._current(shop, output):
            output["decision"] = self._wait("SHOP_STALE")
            return output
        candidates = [slot for slot in shop.get("slots") or []
                      if slot.get("catalog_status") == "unique_name_bound" and
                      type(slot.get("observed_cost")) is int and
                      1 <= slot["observed_cost"] <= 5 and
                      float(slot.get("cost_confidence") or 0) >= .9 and
                      copies[slot["unit_id"]] >= 2 and
                      gold >= slot["observed_cost"]]
        if not candidates:
            output["decision"] = self._fallback_decision(output, "NO_VERIFIED_UPGRADE", visual_candidates)
            return output
        slot = min(candidates, key=lambda row: (row["observed_cost"], row["slot"]))
        output["decision"] = {
            "schema_version": "0.1.0",
            "action": {"type": "buy", "shop_slot": slot["slot"], "unit_id": slot["unit_id"]},
            "confidence": min(.95, float(slot["name_confidence"])),
            "evidence": [{"code": "THIRD_COPY_UPGRADE",
                          "detail": "Two verified one-star copies and a fresh, affordable catalog-bound offer."}],
            "policy": "verified_third_copy_v1",
            "patch": self.patch}
        return output

    @staticmethod
    def _current(section: dict, answer: dict) -> bool:
        cadence = section.get("cadence_delivery")
        if cadence is not None:
            return cadence.get("fresh") is True
        return (type(answer.get("source_ms")) in (int, float) and
                section.get("timestamp_ms") == answer["source_ms"])

    def _economy_block(self, code, **details):
        self._economy_diagnostic=dict(code=code,**details)
        return None

    def _economy_wait(self, fallback):
        result=self._wait(fallback)
        result['economy']=copy.deepcopy(self._economy_diagnostic)
        return result

    def _economy(self, answer: dict) -> dict | None:
        # Every exit states which input or rule stopped the decision. No guessed values.
        rows={}
        for field in ('gold','stage','level','xp'):
            matches=[r for r in answer.get('hud',[]) if r.get('field')==field
                     and r.get('status')=='single_frame_observation'
                     and float(r.get('confidence') or 0)>=.90]
            if len(matches)==1:rows[field]=matches[0]
        missing=[k for k in ('gold','stage','level','xp') if k not in rows]
        if missing:
            self._economy_previous=None
            return self._economy_block('HUD_FIELDS_UNVERIFIED',fields=missing)
        gold,stage,level,xp=[rows[k].get('value') for k in ('gold','stage','level','xp')]
        at=answer.get('source_ms')
        match=re.fullmatch(r'\s*(\d+)\s*/\s*(\d+)\s*',str(rows['xp'].get('text','')))
        if (type(gold) is not int or not 0<=gold<=300 or type(level) is not int or
                not 2<=level<=9 or type(xp) is not int or match is None or
                int(match[1])!=xp or not 0<=xp<int(match[2])<=100 or
                type(at) not in (int,float) or not math.isfinite(at)):
            self._economy_previous=None
            return self._economy_block('HUD_VALUES_INCONSISTENT')
        signature=(stage,level,xp,int(match[2]))
        previous=self._economy_previous
        self._economy_previous=(at,signature)
        window=next((r for r in self.economy_policy['level_windows'] if r['stage']==stage),None)
        if window is None:return self._economy_block('NO_LEVEL_RULE_FOR_STAGE',stage=stage)
        if window['target_level']!=level+1:
            return self._economy_block('LEVEL_WINDOW_NOT_APPLICABLE',level=level,target_level=window['target_level'])
        if previous is None or previous[1]!=signature or not 200<=at-previous[0]<=8000:
            return self._economy_block('ECONOMY_CONFIRMING')
        controls=answer.get('controls') or {}
        if not self._current(controls,answer):return self._economy_block('XP_CONTROLS_STALE')
        active=any(r.get('id')=='buy_xp' and r.get('status')=='observed'
                   and r.get('appearance')=='active_appearance' for r in controls.get('controls',[]))
        if not active:return self._economy_block('XP_BUTTON_UNVERIFIED')
        prices=[r for r in controls.get('numeric_fields',[]) if r.get('id')=='buy_xp_price'
                and r.get('status')=='observed' and float(r.get('confidence') or 0)>=.9]
        if len(prices)!=1 or prices[0].get('value')!=4:
            return self._economy_block('XP_PRICE_UNVERIFIED')
        try:
            quote=self.resource_engine.level_quote(gold=gold,level=level,xp=xp,
                observed_threshold=int(match[2]),reserve=window['reserve_gold'])
        except ValueError:
            return self._economy_block('XP_RULE_MISMATCH')
        cost=quote['gold_cost'];clicks=quote['purchases']
        if not quote['reserve_met']:
            return {'schema_version':'0.1.0',
                    'action':{'type':'hold_econ','target_gold':quote['required_gold'],
                              'missing_gold':quote['missing_gold'],'target_level':quote['target_level']},
                    'confidence':min(r['confidence'] for r in rows.values()),
                    'evidence':[{'code':'SAVE_FOR_LEVEL_RESERVE','stage':stage,
                                 'consecutive_consistent_observations':2}],
                    'resource_quote':quote,'policy':'resource_budget_v1',
                    'strategy_basis':'explicit_tempo_goal_with_exact_resource_cost',
                    'combat_outcome_predicted':False,'patch':self.patch}
        return {'schema_version':'0.1.0',
                'action':{'type':'buy_xp','target_level':level+1,'gold_cost':cost,
                          'purchases':clicks,'gold_after':gold-cost},
                'confidence':min(r['confidence'] for r in rows.values()),
                'evidence':[{'code':'LEVEL_WITH_RESERVE','stage':stage,
                             'observed_xp':rows['xp']['text'],'reserve_gold':window['reserve_gold'],
                             'consecutive_consistent_observations':2}],
                'policy':self.economy_policy['id'],'strategy_basis':'explicit_heuristic',
                'resource_quote':quote,
                'combat_outcome_predicted':False,'patch':self.patch}

    @staticmethod
    def _wait(reason: str) -> dict:
        return {"schema_version": "0.1.0", "action": {"type": "wait"},
                "confidence": 0.0, "evidence": [{"code": reason}],
                "policy": "verified_third_copy_v1"}
