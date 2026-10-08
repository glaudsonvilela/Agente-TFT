"""Evidence-bound messages for a previously recorded match shown on screen."""
from __future__ import annotations
import hashlib
import json
from .shop_name_evidence import readable_name


def _hud_value(answer: dict, field: str):
    rows = [row for row in answer.get('hud') or [] if row.get('field') == field
            and row.get('status') == 'single_frame_observation' and row.get('value') is not None
            and float(row.get('confidence') or 0) >= .85]
    return rows[0]['value'] if len(rows) == 1 else None


def economy_prompt(answer: dict) -> dict:
    """Explain the missing evidence; visible HUD values are not coaching."""
    if answer.get('origin')=='resolution_gate':
        return dict(status='reader_resolution_incompatible',actionable=False,basis=['reader_input_transform'],
                    text='Captura recebida, mas o formato da imagem não é compatível com os leitores. Selecione o vídeo em 16:9, sem bordas.')
    diagnostic=(answer.get('decision') or {}).get('economy') or {}
    code=diagnostic.get('code')
    messages={
        'HUD_VALUES_INCONSISTENT':'Leitura de nível ou XP inconsistente. Mantenha a HUD inteira visível.',
        'NO_LEVEL_RULE_FOR_STAGE':'Não há regra de evolução para este estágio. Consulte a leitura do tabuleiro para as demais recomendações.',
        'LEVEL_WINDOW_NOT_APPLICABLE':'A regra de evolução deste estágio não se aplica ao nível atual.',
        'ECONOMY_CONFIRMING':'Confirmando nível e XP em duas leituras consecutivas.',
        'XP_CONTROLS_STALE':'Leitura do botão de XP desatualizada; aguardando leitura nova.',
        'XP_BUTTON_UNVERIFIED':'Não foi possível reconhecer o botão de compra de XP.',
        'XP_PRICE_UNVERIFIED':'Não foi possível confirmar o preço de compra de XP.',
        'XP_RULE_MISMATCH':'A leitura de XP não corresponde às regras carregadas. Verifique o patch e a leitura.',
        'LEVEL_RESERVE_NOT_MET':'O ouro disponível não atende à reserva exigida pela regra de evolução.'}
    if code=='HUD_FIELDS_UNVERIFIED':
        names={'gold':'ouro','stage':'estágio','level':'nível','xp':'XP'}
        message='Leitura sem confiança suficiente: '+', '.join(names.get(k,k) for k in diagnostic['fields'])+'.'
    else:message=messages.get(code)
    if message:
        return dict(status='economy_blocked',actionable=False,text=message,basis=['decision.'+code],diagnostic=diagnostic)
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
            'text': messages.get(reason, 'Nenhuma decisão disponível. Consulte o diagnóstico de captura e leitura.'),
            'basis': ['hud.gold'] + ([f'decision.{reason}'] if reason else []),
            'actionable': False, 'gold_observed': gold}


def coach_prompt(answer: dict) -> dict:
    """Allow a buy only when a future engine decision matches a current catalog offer."""
    decision = answer.get('decision') or {}
    action = decision.get('action') or {}
    if (answer.get('origin') == 'observed_pixels' and decision.get('policy') == 'attribute_coach_v1'
            and action.get('type') in ('roll', 'composition', 'position', 'equip')):
        recommendations = (answer.get('strategic_coaching') or {}).get('recommendations', [])
        selected = next((r for r in recommendations if r.get('action') == action), None)
        if selected and selected.get('evidence_id') and selected.get('text') == decision.get('text'):
            key = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()[:20]
            return dict(status='action', actionable=True, text=decision['text'],
                speech_text=decision['text'], decision_key='strategy:'+key, speech_max_age_ms=2000,
                basis=['verified_board_state', 'attribute_coach_v1'],
                strategy_basis=decision['scope'], learned_ranker=decision['learned_ranker'],
                recommendations=recommendations)
    if (answer.get('origin') == 'observed_pixels'
            and decision.get('policy') == 'partial_state_live_v1'
            and decision.get('evidence_level') == 'provisional'
            and action.get('type') in ('roll', 'buy_xp', 'buy_pair', 'buy_synergy',
                                       'hold_interest', 'prepare_level')
            and decision.get('decision_key') and decision.get('text')):
        return dict(status='action', actionable=True, text=decision['text'],
            speech_text=decision['text'], decision_key=decision['decision_key'],
            speech_max_age_ms=8000 if action.get('type') == 'prepare_level' else 5000,
            basis=decision['basis'],
            strategy_basis='partial_state_live_v1',
            evidence_level='provisional', policy=decision['policy'],
            family=decision['family'], training_label=False,
            learned_neural_weights=False)
    if (answer.get('origin') == 'observed_pixels' and action.get('type') == 'hold_econ'
            and decision.get('policy') == 'resource_budget_v1'
            and (decision.get('evidence') or [{}])[0].get('code') == 'SAVE_FOR_LEVEL_RESERVE'):
        target,level=action['target_gold'],action['target_level']
        return {'status':'action','actionable':True,
                'text':f'Guarde até {target} de ouro para subir ao nível {level} mantendo a reserva.',
                'speech_text':f'Guarde até {target} de ouro para subir ao nível {level}.',
                'basis':['decision.hold_econ','hud.gold','hud.level','hud.xp'],
                'confidence':decision['confidence'],
                'strategy_basis':decision['strategy_basis'],
                'decision_key':f'save:level:{level}:gold:{target}',
                'speech_max_age_ms':8000}
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
                and readable_name(slot)
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
