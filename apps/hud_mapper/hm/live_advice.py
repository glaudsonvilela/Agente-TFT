"""Partial-state coaching and explicit, session-safe online preference learning.

Advice is a hypothesis about an action, never a label for vision training.
Only player feedback changes preference weights; observed compliance is not
treated as evidence that a recommendation was strategically good.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re
import threading
from pathlib import Path


FAMILIES = ("level", "roll", "buy", "synergy", "economy")


def _hud(answer, field, minimum=.85):
    rows = [row for row in answer.get("hud") or []
            if row.get("field") == field
            and row.get("status") == "single_frame_observation"
            and type(row.get("confidence")) in (int, float)
            and math.isfinite(row["confidence"])
            and row["confidence"] >= minimum]
    return rows[0] if len(rows) == 1 else None


def _hp(answer):
    row = answer.get("hp") or {}
    delivery = answer.get("hp_delivery") or {}
    hp = row.get("hp")
    if (row.get("status") == "accepted" and delivery.get("fresh") is True
            and type(hp) is int and 1 <= hp <= 100):
        return hp
    return None


class LiveAdvice:
    """Small, bounded policy over observed HUD/shop signals and patch arithmetic."""

    def __init__(self, *, economy, windows, champions, preference_path=None):
        self.economy = economy
        self.windows = {row["stage"]: row for row in windows}
        self.champions = champions
        self.preference_path = Path(preference_path) if preference_path else None
        self.lock = threading.Lock()
        self.feedback = {family: [1, 1] for family in FAMILIES}
        self.rated = set()
        if self.preference_path and self.preference_path.is_file():
            try:
                data = json.loads(self.preference_path.read_text(encoding="utf-8"))
                if data.get("schema_version") == 1:
                    for family in FAMILIES:
                        pair = data.get("feedback", {}).get(family)
                        if (isinstance(pair, list) and len(pair) == 2
                                and all(type(n) is int and 1 <= n <= 1000 for n in pair)):
                            self.feedback[family] = pair
            except (OSError, ValueError, TypeError):
                pass

    def rate(self, decision_key, family, helpful):
        if (not isinstance(decision_key, str) or not decision_key.startswith("provisional:")
                or family not in FAMILIES or type(helpful) is not bool):
            return False
        with self.lock:
            if decision_key in self.rated:
                return False
            self.rated.add(decision_key)
            pair = self.feedback[family]
            pair[0 if helpful else 1] = min(1000, pair[0 if helpful else 1] + 1)
            if self.preference_path:
                self.preference_path.parent.mkdir(parents=True, exist_ok=True)
                target = self.preference_path
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_text(json.dumps({"schema_version": 1, "feedback": self.feedback},
                                                sort_keys=True), encoding="utf-8")
                temporary.replace(target)
        return True

    def _priority(self, family, base):
        with self.lock:
            positive, negative = self.feedback[family]
        # Explicit feedback can reorder close alternatives, but cannot override
        # the evidence checks or make an unsupported action appear.
        return base + 0.25 * ((positive / (positive + negative)) - .5)

    def propose(self, answer, visual_candidates=None):
        if answer.get("origin") != "observed_pixels":
            return None
        gold_row = _hud(answer, "gold")
        if gold_row is None:
            return None
        gold = gold_row.get("value")
        if type(gold) is not int or not 0 <= gold <= 300:
            return None
        stage_row, level_row = _hud(answer, "stage"), _hud(answer, "level")
        stage = stage_row.get("value") if stage_row else None
        level = level_row.get("value") if level_row else None
        stage_match = re.fullmatch(r"([2-6])-([1-7])", str(stage))
        level_valid = type(level) is int and 2 <= level <= 10
        options = []
        hp = _hp(answer)
        if (stage_match and level_valid and hp is not None and hp <= 35
                and int(stage_match[1]) >= 3 and level >= 6 and gold >= 34):
            reserve = max(20, min(50, (gold // 10 - 1) * 10))
            rolls = min(2, (gold - reserve) // 2)
            if rolls >= 1:
                options.append((self._priority("roll", .92), "roll",
                    {"type": "roll", "rolls_max": rolls, "reserve_gold": reserve},
                    f"Role até {rolls} vezes agora; pare com pelo menos {reserve} de ouro.",
                    ["hud.stage", "hud.gold", "hud.level", "hud.hp_fresh", "patch.roll_cost"]))

        window = self.windows.get(stage) if stage_match and level_valid else None
        xp_row = _hud(answer, "xp")
        if window and window["target_level"] == level + 1 and xp_row:
            xp = xp_row.get("value")
            xp_text = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", str(xp_row.get("text", "")))
            if type(xp) is int and xp_text and int(xp_text[1]) == xp:
                try:
                    quote = self.economy.level_quote(gold=gold, level=level, xp=xp,
                        observed_threshold=int(xp_text[2]), reserve=window["reserve_gold"])
                except ValueError:
                    quote = None
                if quote and quote["reserve_met"] and quote["gold_cost"] > 0:
                    options.append((self._priority("level", .86), "level",
                        {"type": "buy_xp", "target_level": level + 1,
                         "gold_cost": quote["gold_cost"], "gold_after": quote["gold_after"]},
                        f"Suba ao nível {level + 1} nesta rodada; o cálculo indica {quote['gold_cost']} de ouro. Confira o botão de XP.",
                        ["hud.stage", "hud.gold", "hud.level", "hud.xp", "patch.xp_rules"]))

        # A quiet round before a configured level window is still a useful
        # coaching moment. This is a provisional plan, not a claim that the
        # player's board is strong enough or that XP should be bought now.
        if stage_match and level_valid and gold >= 10:
            current_round = int(stage_match[1]) * 7 + int(stage_match[2])
            upcoming = sorted(
                ((int(match[1]) * 7 + int(match[2]), target, rule)
                 for target, rule in self.windows.items()
                 if (match := re.fullmatch(r"([2-6])-([1-7])", target))
                 and rule["target_level"] == level + 1),
                key=lambda row: row[0])
            for target_round, target, rule in upcoming:
                if 1 <= target_round - current_round <= 3:
                    options.append((self._priority("economy", .48), "economy",
                        {"type": "prepare_level", "target_level": level + 1,
                         "target_stage": target, "reserve_gold": rule["reserve_gold"]},
                        f"Vamos mirar o nível {level + 1} na {target}. Nesta rodada, "
                        "guarde ouro; compre só se a loja fortalecer seu tabuleiro de verdade.",
                        ["hud.stage", "hud.level", "hud.gold", "patch.level_window"]))
                    break

        shop = answer.get("shop") or {}
        cadence = shop.get("cadence_delivery") or {}
        if cadence.get("fresh") is True:
            offers = [row for row in shop.get("slots") or []
                      if row.get("catalog_status") == "unique_name_bound"
                      and row.get("status") == "offer_text_readable"
                      and row.get("unit_id") in self.champions]
            pairs = Counter(row["unit_id"] for row in offers)
            for unit_id, count in pairs.items():
                cost = self.champions[unit_id].get("cost")
                if count < 2 or type(cost) is not int or not 1 <= cost <= 5 or gold < cost * 2:
                    continue
                rows = [row for row in offers if row["unit_id"] == unit_id][:2]
                name = self.champions[unit_id]["name"]
                options.append((self._priority("buy", .69), "buy",
                    {"type": "buy_pair", "unit_id": unit_id,
                     "shop_slots": [row["slot"] for row in rows], "catalog_cost_each": cost},
                    f"Há duas cópias de {name} na loja. Considere comprar o par por {cost * 2} de ouro.",
                    ["shop.two_exact_names", "patch.catalog_cost", "hud.gold"]))
                break

            visual = visual_candidates if isinstance(visual_candidates, dict) else {}
            age = visual.get('age_ms')
            if (visual.get('status') == 'candidate_persistence'
                    and type(age) in (int, float) and math.isfinite(age)
                    and 0 <= age <= 3500):
                board_units = {
                    row.get('candidate_id') for row in visual.get('units') or []
                    if row.get('status') == 'persistent_candidate'
                    and type(row.get('support_frames')) is int
                    and row['support_frames'] >= 2
                    and isinstance(row.get('position'), list)
                    and len(row['position']) == 3
                    and row['position'][0] == 'board'
                    and row.get('candidate_id') in self.champions}
                for offer in offers:
                    unit_id = offer['unit_id']
                    if unit_id in board_units or type(offer.get('slot')) is not int:
                        continue
                    unit = self.champions[unit_id]
                    cost = unit.get('cost')
                    if (type(cost) is not int or not 1 <= cost <= 5 or gold < cost
                            or (type(offer.get('observed_cost')) is int
                                and offer['observed_cost'] != cost)):
                        continue
                    traits = []
                    for trait in unit.get('traits') or []:
                        matching = sorted(id for id in board_units
                                          if trait in (self.champions[id].get('traits') or []))
                        if len(matching) >= 2:
                            traits.append((len(matching), trait, matching))
                    if not traits:
                        continue
                    count, trait, matching = max(traits, key=lambda row: (row[0], row[1]))
                    names = [self.champions[id]['name'] for id in matching[:2]]
                    options.append((self._priority('synergy', .61 + min(count-2, 2)*.02),
                        'synergy',
                        {'type':'buy_synergy', 'unit_id':unit_id, 'shop_slot':offer['slot'],
                         'trait':trait, 'board_unit_ids':matching, 'catalog_cost':cost},
                        f"Compre {unit['name']}: compartilha {trait} com {names[0]} e {names[1]} no tabuleiro.",
                        ['shop.unique_name_bound', 'hub.persistent_board_candidates',
                         'patch.traits', 'hud.gold']))

        if stage_match and 8 <= gold < 50:
            target = ((gold // 10) + 1) * 10
            if target - gold <= 3:
                options.append((self._priority("economy", .54), "economy",
                    {"type": "hold_interest", "target_gold": target},
                    f"Guarde {target - gold} de ouro para chegar a {target} e aumentar os juros, se puder adiar compras.",
                    ["hud.gold", "patch.interest_threshold"]))
        if not options:
            return None
        _, family, action, message, basis = max(options, key=lambda row: row[0])
        key = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()[:20]
        return {"schema_version": "0.1.0", "policy": "partial_state_live_v1",
                "action": action, "text": message, "evidence_level": "provisional",
                "confidence_basis": "observed_partial_state_not_calibrated_success_probability",
                "family": family, "basis": basis,
                "decision_key": "provisional:" + key,
                "training_label": False, "learned_neural_weights": False,
                "evidence": [{"code": "PARTIAL_STATE_HYPOTHESIS"}]}
