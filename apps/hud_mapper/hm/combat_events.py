"""Small, source-time combat outcome observer from confirmed HUD changes.

HP loss is the observed event. Calling it a lost fight also requires a stable
stage and repeated lower HP. This never labels a visual training sample.
"""
from __future__ import annotations

import re

MAX_OCCLUDED_HP_MS = 45_000


def _stage(answer):
    rows = [row for row in answer.get('hud') or []
            if row.get('field') == 'stage'
            and row.get('status') == 'single_frame_observation'
            and float(row.get('confidence') or 0) >= .85
            and re.fullmatch(r'[1-9]-[1-9]', str(row.get('value') or ''))]
    return rows[0]['value'] if len(rows) == 1 else None


def _hp(answer):
    row = answer.get('hp') or {}
    hp = row.get('hp')
    if (row.get('status') == 'accepted' and type(hp) is int and 0 <= hp <= 100
            and float(row.get('confidence') or 0) >= .8
            and (answer.get('hp_delivery') or {}).get('fresh', True)):
        return hp
    return None


def _adjacent(previous, current):
    if previous == current:
        return True
    a, b = map(int, previous.split('-'))
    c, d = map(int, current.split('-'))
    return (a == c and d == b + 1) or (c == a + 1 and b >= 6 and d == 1)


class CombatEvents:
    def __init__(self):
        self.epoch = self.last_ms = self.stage = self.baseline = None
        self.baseline_reads = 0
        self.pending = None
        self.announced_stage = None

    def _reset(self, epoch, ms, stage, hp):
        self.epoch, self.last_ms, self.stage = epoch, ms, stage
        self.baseline, self.baseline_reads = hp, 1
        self.pending = None
        self.announced_stage = None

    def update(self, answer, *, epoch, source_ms):
        stage, hp = _stage(answer), _hp(answer)
        if stage is None or hp is None or not isinstance(source_ms, (int, float)):
            return None
        if (self.epoch != epoch or self.last_ms is None
                or source_ms <= self.last_ms
                # The standings can be hidden by the Damage Dealt panel for
                # most of a fight. Keep the last stable HP through one round.
                or source_ms - self.last_ms > MAX_OCCLUDED_HP_MS
                or not _adjacent(self.stage, stage)):
            self._reset(epoch, source_ms, stage, hp)
            return None
        self.last_ms, self.stage = source_ms, stage
        if hp > self.baseline:
            self._reset(epoch, source_ms, stage, hp)
            return None
        if hp == self.baseline:
            self.baseline_reads = min(3, self.baseline_reads + 1)
            self.pending = None
            return None
        if self.baseline_reads < 2 or self.announced_stage == stage:
            return None
        if (self.pending is None or hp < self.pending['hp']
                or source_ms - self.pending['first_ms'] > 5000):
            self.pending = dict(hp=hp, first_ms=source_ms, reads=1)
            return None
        if hp != self.pending['hp']:
            self.pending = None
            return None
        self.pending['reads'] += 1
        if self.pending['reads'] < 2 or source_ms - self.pending['first_ms'] < 500:
            return None
        before, after = self.baseline, hp
        self.baseline, self.baseline_reads = hp, 2
        self.pending = None
        self.announced_stage = stage
        damage = before-after
        text = (f'Essa luta custou {damage} de vida. Não dá para repetir isso: veja quem caiu primeiro e proteja sua fonte de dano na próxima.'
                if damage >= 10 else
                f'Não foi dessa vez, hein. Perdemos {damage} de vida; um pequeno ajuste de posição pode ajudar na próxima.'
                if damage <= 5 else
                f'Perdemos {damage} de vida nessa luta. Veja quem ficou exposto e ajuste antes da próxima rodada.')
        return dict(event='combat_loss_observed', stage=stage, hp_before=before,
                    hp_after=after, damage=damage, source_ms=source_ms,
                    basis=['hud.stage', 'player.hp.temporal_drop'],
                    training_label=False, outcome_prediction=False,
                    result_verified=False, inference='repeated_hp_drop_with_stable_stage',
                    text=text)
