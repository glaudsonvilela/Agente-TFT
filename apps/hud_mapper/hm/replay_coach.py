"""Small, evidence-bound coaching prompts for a previously recorded match on screen."""
from __future__ import annotations


def _hud_value(answer: dict, field: str):
    rows = [row for row in answer.get('hud') or [] if row.get('field') == field
            and row.get('status') == 'single_frame_observation' and row.get('value') is not None]
    return rows[0]['value'] if len(rows) == 1 else None


def economy_prompt(answer: dict) -> dict:
    gold = _hud_value(answer, 'gold')
    stage = _hud_value(answer, 'stage')
    level = _hud_value(answer, 'level')
    if type(gold) is not int or not 0 <= gold <= 300:
        return {'status': 'abstain_missing_gold', 'text': 'Aguardando leitura confiável de ouro para comentar a economia.',
                'basis': [], 'actionable': False}
    context = f'No estágio {stage}, nível {level}, ' if stage is not None and level is not None else ''
    if gold >= 40:
        message = 'revise se preservar ouro ou investir neste momento teria dado mais força ao tabuleiro.'
    elif gold >= 15:
        message = 'compare o resultado de economizar com o de fortalecer o tabuleiro neste momento.'
    else:
        message = 'revise as compras e rolagens anteriores e o efeito delas na força do tabuleiro.'
    return {'status': 'review_prompt', 'text': f'{context}ouro observado: {gold}; {message}',
            'basis': ['hud.gold'] + (['hud.stage', 'hud.level'] if context else []),
            'actionable': False, 'gold_observed': gold}


def inventory_prompt(snapshot: dict) -> dict | None:
    inventory = snapshot.get('inventory') or {}
    count = len(inventory.get('candidate_slots') or [])
    if count == 0:
        return None
    return {'status': 'review_prompt',
            'text': f'{count} espaço(s) com ícone candidato no inventário; revise no vídeo quando equipar ou guardar os itens.',
            'basis': ['hub.inventory.icon_candidate'], 'actionable': False,
            'item_identity_established': False}
