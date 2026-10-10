"""Rank visual champion hypotheses with observed shop and pool context.

This is a conditional ranking over the recognizer's candidates, not a
calibrated probability that a champion is present. In particular, current
shop odds cannot rule out a unit purchased at an earlier level.
"""

from __future__ import annotations

from collections import Counter, deque
import math


def _stage_number(value):
    if not isinstance(value, str):
        return None
    first = value.split('-', 1)[0]
    return int(first) if first.isdigit() and 1 <= int(first) <= 9 else None


class TemporalVisualHypotheses:
    """Display one track's repeated guesses without calling them probabilities.

    Consecutive video frames are correlated. Count their top names as votes;
    do not multiply their model scores or change the confirmed game state.
    A different name replaces the displayed guess only after winning a
    strict majority in the five most recent observations.
    """

    def __init__(self, window=5):
        if type(window) is not int or window < 3 or window % 2 != 1:
            raise ValueError('Window must be an odd integer >= 3')
        self.window = window
        self.history = {}
        self.displayed = {}

    def update(self, track_id, candidates):
        if not isinstance(track_id, (str, int)) or not candidates:
            return dict(status='no_visual_vote', identity_verified=False)
        top = candidates[0].get('unit_id') if isinstance(candidates[0], dict) else None
        if not isinstance(top, str) or not top:
            return dict(status='no_visual_vote', identity_verified=False)
        votes = self.history.setdefault(track_id, deque(maxlen=self.window))
        votes.append(top)
        counts = Counter(votes)
        incumbent = self.displayed.get(track_id)
        if incumbent is None:
            incumbent = top
        else:
            challenger, count = counts.most_common(1)[0]
            if challenger != incumbent and count > len(votes) // 2 and count >= 3:
                incumbent = challenger
        self.displayed[track_id] = incumbent
        return dict(status='temporal_visual_candidate', unit_id=incumbent,
                    votes_for_displayed=counts[incumbent], window_observations=len(votes),
                    conflicting_top1=len(counts) > 1, identity_verified=False,
                    calibrated_probability=False)


class ChampionBelief:
    def __init__(self, catalog):
        self.rules = catalog['economy']
        self.champions = catalog['champions']
        self.shop = catalog['shop_champions']
        self.by_cost = Counter(row['cost'] for row in self.shop.values())
        self.patch = catalog['patch']
        self.set_key = catalog['set_key']

    def _confirmed_copies(self, holdings):
        """Count a physical unit once, across board and bench observations."""
        copies, seen = Counter(), set()
        for row in holdings or []:
            if not isinstance(row, dict) or row.get('identity_verified') is not True:
                continue
            player, track = row.get('player'), row.get('track_id')
            champion = row.get('champion_id')
            stars = row.get('stars')
            if (not isinstance(player, str) or not player or
                    not isinstance(track, (str, int)) or isinstance(track, bool) or
                    champion not in self.champions or type(stars) is not int or
                    not 1 <= stars <= 3 or (player, track) in seen):
                continue
            seen.add((player, track))
            identity = self.champions[champion]['pool_identity']
            if identity in self.shop:
                copies[identity] += 3 ** (stars - 1)
        return copies

    def shop_slot(self, *, level, stage=None, confirmed_holdings=None):
        """Exact one-slot distribution in the explicitly observed-only pool.

        This conditional calculation is not the actual shop probability when
        other players hold unseen copies. It makes that assumption visible.
        """
        if type(level) is not int or str(level) not in self.rules['shop_odds']:
            return dict(status='level_unavailable', probabilities={})
        copies = self._confirmed_copies(confirmed_holdings)
        remaining = {unit_id: max(0, self.rules['pool_by_cost'][str(row['cost'])]
                                     - copies[unit_id])
                     for unit_id, row in self.shop.items()}
        tier_totals = {cost: sum(remaining[unit_id] for unit_id, row in self.shop.items()
                                 if row['cost'] == cost)
                       for cost in range(1, 6)}
        odds = self.rules['shop_odds'][str(level)]
        probabilities = {unit_id: (odds[row['cost'] - 1] * remaining[unit_id] /
                                    tier_totals[row['cost']]
                                    if tier_totals[row['cost']] else 0.0)
                         for unit_id, row in self.shop.items()}
        return dict(status='conditional_exact_one_shop_slot',
                    probabilities=probabilities, level=level,
                    stage=stage if _stage_number(stage) is not None else None,
                    confirmed_holding_copies=dict(copies),
                    assumption='all_unobserved_holdings_are_zero',
                    actual_probability_known=False,
                    formula='tier_odds * remaining_copies / remaining_tier_copies',
                    patch=self.patch, set_key=self.set_key)

    def observed_offers(self, offers, *, level, stage=None,
                        confirmed_holdings=None):
        """Attach base-roll math to OCR-bound shop cards, not to unit bodies."""
        distribution = self.shop_slot(level=level, stage=stage,
                                      confirmed_holdings=confirmed_holdings)
        rows = []
        for row in offers or []:
            if not isinstance(row, dict) or row.get('status') != 'offer_text_readable' \
                    or row.get('catalog_status') != 'unique_name_bound':
                continue
            unit_id = row.get('unit_id')
            if unit_id not in self.shop or type(row.get('slot')) is not int:
                continue
            rows.append(dict(slot=row['slot'], observed_name=row.get('observed_name'),
                             unit_id=unit_id, name_source='shop_ocr_unique_catalog_match',
                             chance_next_slot_if_no_hidden_holdings=
                             distribution['probabilities'].get(unit_id),
                             body_identity_verified=False))
        return rows

    def _single_addition_trait_factor(self, transition):
        """A measured +1 trait delta can exclude incompatible new units.

        The panel alone cannot prove which unit moved. Require a separately
        verified single-unit board addition with no other roster/item change.
        Missing panel rows are unknown, never interpreted as zero.
        """
        if not isinstance(transition, dict) or any(transition.get(key) is not True
            for key in ('same_player_verified', 'single_unit_added_verified',
                        'other_units_unchanged_verified', 'equipment_unchanged_verified')):
            return None
        before, after = transition.get('counts_before'), transition.get('counts_after')
        if not isinstance(before, dict) or not isinstance(after, dict):
            return None
        increased = set()
        for trait in before.keys() & after.keys():
            old, new = before[trait], after[trait]
            if (not isinstance(trait, str) or type(old) is not int or
                    type(new) is not int or not 0 <= old <= 9 or not 0 <= new <= 9):
                return None
            if new < old or new - old > 1:
                return None
            if new == old + 1:
                increased.add(trait)
        if not increased:
            return None
        factor = {}
        for unit_id in self.shop:
            traits = self.champions.get(unit_id, {}).get('traits')
            # A missing catalog trait is unknown, not evidence against a unit.
            factor[unit_id] = float(traits is None or increased <= set(traits))
        return factor

    def acquisition_belief(self, *, level, stage=None, confirmed_holdings=None,
                           evidence=(), confirmed_identity=None,
                           trait_transition=None):
        """Combine an acquisition prior with independent measured evidence.

        Each evidence row is ``{source_group, likelihoods, provenance}``.
        ``likelihoods`` must be P(observation | champion), measured on held-out
        examples for the same observation pipeline. Multiple cues from the
        same image belong to one source group: multiplying colour, silhouette
        and classifier outputs from one crop would count the pixels repeatedly.
        This applies only to a *new shop acquisition*. Existing units use
        their tracked history, not today's shop odds.
        """
        if confirmed_identity is not None:
            if confirmed_identity not in self.shop:
                raise ValueError('Unknown confirmed champion')
            return dict(status='confirmed_acquisition', identity_verified=True,
                        hypotheses=[dict(unit_id=confirmed_identity, probability=1.0,
                                         source='confirmed_shop_to_track_transfer')])
        prior = self.shop_slot(level=level, stage=stage,
                               confirmed_holdings=confirmed_holdings)
        if prior['status'] != 'conditional_exact_one_shop_slot':
            return dict(status='prior_unavailable', identity_verified=False,
                        hypotheses=[], shop_slot=prior)
        groups = set()
        factors = []
        for row in evidence:
            if not isinstance(row, dict):
                raise ValueError('Evidence row must be a mapping')
            group, likelihoods, provenance = (row.get('source_group'),
                row.get('likelihoods'), row.get('provenance'))
            if (not isinstance(group, str) or not group or group in groups or
                    not isinstance(provenance, str) or not provenance or
                    not isinstance(likelihoods, dict) or not likelihoods or
                    any(unit_id not in self.shop or type(value) not in (int, float)
                        or not math.isfinite(value) or not 0 <= value <= 1
                        for unit_id, value in likelihoods.items())):
                raise ValueError('Evidence needs unique source, provenance and valid likelihoods')
            groups.add(group)
            factors.append((group, likelihoods, provenance))
        trait_factor = self._single_addition_trait_factor(trait_transition)
        if trait_factor is not None:
            if 'verified_trait_delta' in groups:
                raise ValueError('Trait delta supplied twice')
            factors.append(('verified_trait_delta', trait_factor,
                            'single_unit_board_addition_and_confirmed_trait_counts'))
        if not factors:
            return dict(status='prior_only', identity_verified=False,
                        hypotheses=[], shop_slot=prior,
                        reason='No measured likelihoods; visual confidence is not a likelihood')
        # A missing likelihood is neutral rather than impossible. This lets a
        # feature measured for only some units preserve unknown alternatives.
        weights = {unit_id: chance * math.prod(likelihoods.get(unit_id, 1.0)
                           for _, likelihoods, _ in factors)
                   for unit_id, chance in prior['probabilities'].items()}
        total = sum(weights.values())
        if total <= 0:
            return dict(status='conflicting_evidence', identity_verified=False,
                        hypotheses=[], shop_slot=prior)
        hypotheses = [dict(unit_id=unit_id, probability=weight / total)
                      for unit_id, weight in weights.items() if weight > 0]
        hypotheses.sort(key=lambda row: row['probability'], reverse=True)
        return dict(status='conditional_acquisition_posterior',
                    identity_verified=False, hypotheses=hypotheses,
                    source_groups=[dict(source_group=group, provenance=provenance)
                                   for group, _, provenance in factors],
                    assumption='new_random_shop_slot; independent_source_groups; '
                               'supplied_likelihoods_valid; unseen_holdings_zero',
                    actual_probability_known=False, shop_slot=prior)

    def rank(self, candidates, *, level=None, stage=None, confirmed_holdings=None,
             confirmed_identity=None):
        """Return a weak contextual reranking of visual candidates.

        Visual scores are uncalibrated and top-k is incomplete. Therefore
        neither the normalized weights nor the margin are identity guarantees.
        """
        if confirmed_identity in self.champions:
            return dict(status='carried_confirmed_identity',
                        hypotheses=[dict(unit_id=confirmed_identity,
                                         source='confirmed_shop_to_bench_or_board_track')],
                        identity_verified=True,
                        shop_slot=self.shop_slot(level=level, stage=stage,
                                                 confirmed_holdings=confirmed_holdings))
        valid = []
        for row in candidates or []:
            if not isinstance(row, dict):
                continue
            unit_id = row.get('unit_id')
            score = row.get('score_uncalibrated', row.get('score'))
            if (unit_id not in self.champions or type(score) not in (int, float)
                    or not math.isfinite(score) or not 0 <= score <= 1):
                continue
            valid.append((unit_id, float(score)))
        if not valid:
            return dict(status='no_visual_candidates', hypotheses=[],
                        identity_verified=False)
        valid = list(dict((unit_id, score) for unit_id, score in valid).items())
        level_ok = type(level) is int and str(level) in self.rules['shop_odds']
        stage_num = _stage_number(stage)
        shop = self.shop_slot(level=level, stage=stage,
                              confirmed_holdings=confirmed_holdings)
        copies = self._confirmed_copies(confirmed_holdings)
        # These scores remain visual hypotheses. Current shop odds do not
        # revise existing-board identity: units persist across stages/levels.
        weighted = []
        for unit_id, visual in valid:
            data = self.champions[unit_id]
            identity = data['pool_identity']
            cost = data['cost']
            pool_size = self.rules['pool_by_cost'].get(str(cost), 0)
            if identity in self.shop and pool_size:
                remaining = max(0, pool_size - copies[identity])
                slot_chance = shop['probabilities'].get(identity) if level_ok else None
            else:
                remaining, slot_chance = None, None
            weighted.append(dict(unit_id=unit_id, visual_score_uncalibrated=visual,
                                 cost=cost, known_remaining_upper_bound=remaining,
                                 shop_slot_if_no_hidden_holdings=slot_chance))
        ranked = sorted(weighted,
                        key=lambda row: row['visual_score_uncalibrated'], reverse=True)
        return dict(status='conditional_candidate_ranking', hypotheses=ranked,
                    stage=stage if stage_num is not None else None,
                    level=level if level_ok else None,
                    confirmed_holding_copies=dict(copies),
                    pool_observation='confirmed_visible_holdings_only',
                    shop_slot=shop,
                    patch=self.patch, set_key=self.set_key,
                    identity_verified=False, calibrated_probability=False,
                    candidate_set_complete=False)
