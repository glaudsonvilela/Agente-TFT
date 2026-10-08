"""Split local observation caches when a captured game returns to early rounds."""
from __future__ import annotations

import hashlib
import re


class MatchIdentity:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.generation = 0
        self.last_round = None
        self.reset_votes = 0

    def observe(self, stage: str | None) -> str:
        match = re.fullmatch(r'([1-9])-([1-7])', stage or '')
        if match:
            current = int(match[1]) * 7 + int(match[2])
            previous = self.last_round
            if previous is not None and previous >= 3 * 7 + 1 and current <= 2 * 7 + 3:
                self.reset_votes += 1
                if self.reset_votes >= 2:
                    self.generation += 1
                    self.last_round = current
                    self.reset_votes = 0
            else:
                self.reset_votes = 0
                if previous is None or current >= previous:
                    self.last_round = current
        return hashlib.sha256(f'{self.session_id}:{self.generation}'.encode('utf-8')).hexdigest()[:32]
