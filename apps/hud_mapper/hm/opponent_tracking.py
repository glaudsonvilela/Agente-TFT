"""Track visible scoreboard names and HP without assigning unverified boards.

Ranking rows may move; normalized names are the local identity keys. OCR is
kept as screen evidence, never as an account lookup or training label.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import threading
import unicodedata

ROWS = (289, 369, 449, 529, 609, 689, 769)


def _clean(value):
    normalized = unicodedata.normalize('NFKC', str(value or ''))
    return re.sub(r'\s+', ' ', re.sub(r'[^\w ]+', ' ', normalized)).strip()


def _key(value):
    return re.sub(r'[^\w]+', '', _clean(value).casefold())


def parse_panel(panel):
    if not isinstance(panel, dict) or panel.get('status') not in (
            'raw_ocr', 'cadence_cached', 'exact_pixels_cached'):
        return []
    words_all = panel.get('words') or []
    # The same right-hand space can show damage statistics instead of standings.
    # A numeric damage value must never become an opponent's HP.
    heading = {_key(word.get('text')) for word in words_all
               if (word.get('box') or [0, 0])[1] < 320}
    if 'damage' in heading and 'dealt' in heading:
        return []
    buckets = [[] for _ in ROWS]
    for word in panel.get('words') or []:
        box = word.get('box') or []
        if len(box) != 4:
            continue
        center = (box[1] + box[3]) / 2
        index = min(range(len(ROWS)), key=lambda i: abs(center - ROWS[i]))
        if abs(center - ROWS[index]) <= 17:
            buckets[index].append(word)
    parsed = []
    for index, words in enumerate(buckets):
        names = [word for word in words
                 if 1710 <= word['box'][0] < 1830 and word['box'][2] <= 1830
                 and word['box'][3] - word['box'][1] <= 20
                 and float(word.get('confidence') or 0) >= .45
                 and len(_clean(word.get('text'))) >= 2]
        names.sort(key=lambda word: word['box'][0])
        name = _clean(' '.join(word['text'] for word in names))
        values = [(_clean(word.get('text')), float(word.get('confidence') or 0))
                  for word in words if 1830 <= word['box'][0] <= 1855
                  and word['box'][2] <= 1865]
        numbers = [int(re.sub(r'\D', '', text)) for text, confidence in values
                   if confidence >= .60 and re.fullmatch(r'\D*\d{1,3}\D*', text)
                   and 0 <= int(re.sub(r'\D', '', text)) <= 100]
        if len(_key(name)) >= 3 and any(char.isalpha() for char in name):
            parsed.append(dict(row=index, name=name, key=_key(name),
                               hp=numbers[0] if len(numbers) == 1 else None))
    return parsed


def _battle_name(panel):
    words = [row for row in panel.get('battle_name_words') or []
             if float(row.get('confidence') or 0) >= .35]
    words.sort(key=lambda row: (row.get('box') or [0])[0])
    return _clean(' '.join(row.get('text') or '' for row in words))


class OpponentTracker:
    def __init__(self):
        self.lock = threading.RLock()
        self.epoch = self.last_ocr_frame = None
        self.players = {}
        self.current_key = None
        self.current_votes = 0
        self.last_panel_ms = None

    def update(self, panel, *, epoch, source_ms):
        with self.lock:
            if self.epoch != epoch or (self.last_panel_ms is not None and source_ms < self.last_panel_ms):
                self.players.clear()
                self.current_key = None
                self.current_votes = 0
                self.last_ocr_frame = None
            self.epoch = epoch
            if not isinstance(panel, dict):
                return self.snapshot(source_ms)
            ocr_frame = panel.get('frame_id')
            if ocr_frame == self.last_ocr_frame:
                return self.snapshot(source_ms)
            self.last_ocr_frame = ocr_frame
            self.last_panel_ms = source_ms
            for row in parse_panel(panel):
                player = self.players.setdefault(row['key'], dict(
                    name=row['name'], hp=None, row=row['row'], reads=0,
                    hp_pending=None, last_seen_ms=source_ms, losses_observed=0))
                player['reads'] += 1
                player['row'] = row['row']
                player['last_seen_ms'] = source_ms
                if player['reads'] >= 2:
                    player['name'] = row['name']
                if row['hp'] is not None:
                    pending = player['hp_pending']
                    if player['hp'] == row['hp']:
                        player['hp_pending'] = None
                    elif pending and pending['value'] == row['hp']:
                        player['hp'] = row['hp']
                        player['hp_pending'] = None
                    else:
                        player['hp_pending'] = dict(value=row['hp'], first_ms=source_ms)
            # The name over a Little Legend is just a candidate until it
            # matches a repeatedly read scoreboard entry across two OCR runs.
            battle = _key(_battle_name(panel))
            matches = [(key, SequenceMatcher(None, battle, key).ratio())
                       for key, player in self.players.items()
                       if player['reads'] >= 2 and len(battle) >= 3]
            matches = sorted((row for row in matches if row[1] >= .88),
                             key=lambda row: row[1], reverse=True)
            candidate = matches[0][0] if matches and (len(matches) == 1 or
                         matches[0][1] - matches[1][1] >= .08) else None
            if candidate == self.current_key and candidate is not None:
                self.current_votes += 1
            else:
                self.current_key, self.current_votes = candidate, 1 if candidate else 0
            # Bounded state: old OCR ghosts do not accumulate indefinitely.
            self.players = {key: player for key, player in self.players.items()
                            if source_ms - player['last_seen_ms'] <= 120000}
            return self.snapshot(source_ms)

    def register_loss(self, event, *, epoch, source_ms):
        with self.lock:
            if (self.epoch != epoch or self.current_votes < 2 or not self.current_key
                    or self.last_panel_ms is None or source_ms - self.last_panel_ms > 10000):
                return None
            player = self.players.get(self.current_key)
            if not player:
                return None
            player['losses_observed'] += 1
            return dict(opponent_name=player['name'],
                        opponent_key=self.current_key,
                        link_status='scoreboard_and_battle_label_temporal_candidate',
                        event=event['event'], stage=event['stage'],
                        training_label=False)

    def snapshot(self, source_ms):
        with self.lock:
            players = [dict(name=row['name'] if row['reads'] >= 2 else None,
                            hp=row['hp'], row=row['row'], reads=row['reads'],
                            last_seen_age_ms=max(0, source_ms-row['last_seen_ms']),
                            losses_observed=row['losses_observed'],
                            status='persistent_candidate' if row['reads'] >= 2 else 'observing')
                       for row in self.players.values()
                       if source_ms-row['last_seen_ms'] <= 120000]
            players.sort(key=lambda row: row['row'])
            current = (self.players.get(self.current_key)
                       if self.current_votes >= 2 and self.last_panel_ms is not None
                       and source_ms-self.last_panel_ms <= 10000 else None)
            return dict(status='screen_candidates', players=players,
                        current_opponent=current['name'] if current else None,
                        current_opponent_status='temporal_candidate' if current else 'unresolved',
                        player_identity_verified=False,
                        opponent_board_assigned=False, training_label=False)
