"""Evidence-bound messages for a previously recorded match shown on screen."""
from __future__ import annotations


def _hud_value(answer: dict, field: str):
    rows = [row for row in answer.get('hud') or [] if row.get('field') == field
            and row.get('status') == 'single_frame_observation' and row.get('value') is not None
            and float(row.get('confidence') or 0) >= .85]
    return rows[0]['value'] if len(rows) == 1 else None


def economy_prompt(answer: dict) -> dict:
    """Explain the missing evidence; visible HUD values are not coaching."""
    gold = _hud_value(answer, 'gold')
    if type(gold) is not int or not 0 <= gold <= 300:
        return {'status': 'abstain_missing_gold', 'text': 'Aguardando leitura confiável de ouro.',
                'basis': [], 'actionable': False}
    evidence = (answer.get('decision') or {}).get('evidence') or []
    reason = evidence[0].get('code') if evidence else None
    messages = {
        'OWNED_UNITS_UNVERIFIED': 'Aguardando identificação confiável dos campeões no tabuleiro.',
        'OWNED_UNITS_STALE': 'Aguardando nova leitura dos campeões no tabuleiro.',
        'SHOP_STALE': 'Aguardando leitura atual da loja.',
        'NO_VERIFIED_UPGRADE': 'Nenhuma compra com melhoria confirmada neste momento.',
    }
    return {'status': 'awaiting_decision',
            'text': messages.get(reason, 'Analisando tabuleiro e loja para uma ação verificável.'),
            'basis': ['hud.gold'] + ([f'decision.{reason}'] if reason else []),
            'actionable': False, 'gold_observed': gold}


def coach_prompt(answer: dict) -> dict:
    """Allow a buy only when a future engine decision matches a current catalog offer."""
    decision = answer.get('decision') or {}
    action = decision.get('action') or {}
    if (answer.get('origin') == 'observed_pixels' and action.get('type') == 'buy_xp'
            and decision.get('policy') == 'replay_standard_tempo_v1'
            and (decision.get('evidence') or [{}])[0].get('code') == 'LEVEL_WITH_RESERVE'):
        level,cost,left=action['target_level'],action['gold_cost'],action['gold_after']
        return {'status':'action','actionable':True,
                'text':f'Suba para o nível {level} por {cost} de ouro. Restam {left} de ouro.',
                'speech_text':f'Suba para o nível {level}. Gaste {cost} de ouro.',
                'basis':['decision.buy_xp','hud.stage','hud.gold','hud.level','hud.xp','controls.buy_xp_price'],
                'confidence':decision['confidence'],'strategy_basis':'explicit_heuristic',
                'decision_key':f'level:{level}:cost:{cost}', 'speech_max_age_ms':8000}
    if (answer.get('origin') == 'observed_pixels' and action.get('type') == 'buy'
            and float(decision.get('confidence') or 0) >= .8
            and decision.get('evidence') and type(action.get('shop_slot')) is int):
        slot_index = action['shop_slot']
        shop = answer.get('shop') or {}
        cadence = shop.get('cadence_delivery') or {}
        slot = next((row for row in shop.get('slots') or [] if row.get('slot') == slot_index), None)
        gold = _hud_value(answer, 'gold')
        if (cadence.get('fresh', True) and slot is not None
                and slot.get('status') == 'offer_text_readable'
                and slot.get('unit_id') and slot.get('unit_id') == action.get('unit_id')
                and float(slot.get('name_confidence') or 0) >= .9
                and type(slot.get('observed_cost')) is int and type(gold) is int
                and gold >= slot['observed_cost']):
            name = slot.get('observed_name')
            if isinstance(name, str) and 1 <= len(name) <= 40:
                return {'status': 'action', 'text': f'Compre {name} agora, na posição {slot_index+1} da loja.',
                        'speech_text': f'Compre {name} agora.',
                        'basis': ['decision.buy', f'shop.{slot_index}.name', 'hud.gold'],
                        'actionable': True, 'confidence': decision['confidence'],
                        'unit_id': slot['unit_id'],
                        'decision_key': f'buy:{slot_index}:{slot["unit_id"]}',
                        'speech_max_age_ms': 3000}
    return economy_prompt(answer)


def inventory_prompt(snapshot: dict) -> dict | None:
    """A candidate icon alone is never an equipment instruction."""
    action = snapshot.get('verified_action') or {}
    if (action.get('type') != 'equip' or float(action.get('confidence') or 0) < .9
            or not action.get('item_name') or not action.get('unit_name')
            or not action.get('item_id') or not action.get('unit_id')):
        return None
    return {'status': 'action',
            'text': f'Equipe {action["item_name"]} em {action["unit_name"]} agora.',
            'speech_text': f'Equipe {action["item_name"]} em {action["unit_name"]} agora.',
            'basis': ['hub.verified_action'], 'actionable': True,
            'item_identity_established': True, 'confidence': action['confidence']}
