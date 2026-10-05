"""Small runtime adapter for the simulator's tested economic arithmetic.

This is an exact resource quote, not a trained policy or a combat forecast.
All tables load once, outside the capture loop. No network or tensor runtime.
"""

import hashlib
import json
from pathlib import Path

from trainer.simulation.economy import grant_xp, validate_economy
from trainer.simulation.round_economy import interest, validate_rules
from trainer.simulation.state import Player


class EconomyBudget:
    def __init__(self, root, *, patch, set_key):
        root = Path(root).resolve()
        self.manifest = json.loads(
            (root / "configs/contexts/replay-resource-engine-v1.json").read_text()
        )
        if self.manifest.get("schema_version") != 1 or (
            self.manifest.get("tft_patch"),
            self.manifest.get("set_key"),
        ) != (patch, set_key):
            raise ValueError("resource budget belongs to another patch")
        loaded = {}
        for name in ("round_economy", "profile"):
            entry = self.manifest["components"][name]
            path = (root / entry["path"]).resolve(strict=True)
            if not path.is_relative_to(root):
                raise ValueError("resource budget path escapes package")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("resource budget table checksum mismatch")
            loaded[name] = json.loads(raw)
        self.rules = loaded["round_economy"]
        self.content = {"economy": loaded["profile"]["planning"]["economy"]}
        validate_rules(self.rules)
        validate_economy(self.content)
        self.identity = hashlib.sha256(
            json.dumps(self.manifest, sort_keys=True).encode()
        ).hexdigest()

    def level_quote(self, *, gold, level, xp, observed_threshold, reserve):
        if any(type(value) is not int or value < 0 for value in (gold, xp, reserve)):
            raise ValueError("invalid observed economic resources")
        rules = self.content["economy"]
        threshold = rules["xp_to_next"].get(str(level))
        if (
            type(level) is not int
            or threshold is None
            or type(observed_threshold) is not int
            or threshold != observed_threshold
            or xp >= threshold
        ):
            raise ValueError("observed XP threshold differs from bound rules")
        purchases = (threshold - xp + rules["xp_amount"] - 1) // rules["xp_amount"]
        cost = purchases * rules["xp_cost"]
        player = Player(gold, level, xp)
        grant_xp(player, purchases * rules["xp_amount"], self.content)
        after = gold - cost
        return dict(
            engine="resource_budget_v1",
            engine_identity=self.identity,
            scope="economy_only",
            learned_policy=False,
            abilities_used=False,
            target_level=player.level,
            target_xp=player.xp,
            purchases=purchases,
            gold_cost=cost,
            gold_after=after if after >= 0 else None,
            reserve_gold=reserve,
            required_gold=cost + reserve,
            missing_gold=max(0, cost + reserve - gold),
            affordable=after >= 0,
            reserve_met=after >= reserve,
            interest_now=interest(gold, self.rules),
            interest_after=interest(after, self.rules) if after >= 0 else None,
            interest_basis="current gold only; excludes future wins and seasonal rewards",
        )
