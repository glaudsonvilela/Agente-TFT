"""Local neural combat value, bound to a simulator/content revision.

This estimates a fight, not match placement or the future value of spending gold.
Unknown identities are errors: an unseen champion must never become an empty cell.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np


ENCODER = "combat_hex_cells_v2"
ROWS, COLUMNS = 4, 7


class BoardEncoder:
    def __init__(self, champions, items):
        self.champions = tuple(champions)
        self.items = tuple(items)
        if (
            not self.champions
            or len(set(champions)) != len(champions)
            or len(set(items)) != len(items)
        ):
            raise ValueError("Encoder identities must be unique and nonempty")
        self.champion_index = {name: i for i, name in enumerate(champions)}
        self.item_index = {name: i for i, name in enumerate(items)}
        self.cell_features = len(champions) + 1 + len(items)
        self.size = 2 * ROWS * COLUMNS * self.cell_features

    def encode(self, teams):
        if len(teams) != 2:
            raise ValueError("Combat value requires two observed teams")
        result = np.zeros((2, ROWS, COLUMNS, self.cell_features), dtype=np.float32)
        for side, team in enumerate(teams):
            if team.augments:
                raise ValueError("Augments are outside this model training scope")
            occupied = set()
            for unit in team.units:
                if unit.zone != "board":
                    continue
                if unit.champion not in self.champion_index:
                    raise ValueError(
                        f"Champion outside neural training vocabulary: {unit.champion}"
                    )
                if (
                    len(unit.position) != 2
                    or any(type(v) is not int for v in unit.position)
                    or not 0 <= unit.position[0] < ROWS
                    or not 0 <= unit.position[1] < COLUMNS
                    or unit.position in occupied
                    or type(unit.stars) is not int
                    or not 1 <= unit.stars <= 3
                ):
                    raise ValueError(
                        "Invalid, duplicate or unsupported board position/stars"
                    )
                if len(unit.items) > 3 or any(
                    item not in self.item_index for item in unit.items
                ):
                    raise ValueError(
                        "Equipped items outside neural training vocabulary"
                    )
                if unit.permanent:
                    raise ValueError(
                        "Permanent stacks are outside this model training scope"
                    )
                occupied.add(unit.position)
                cell = result[side, unit.position[0], unit.position[1]]
                cell[self.champion_index[unit.champion]] = 1
                cell[len(self.champions)] = unit.stars / 3
                for item in unit.items:
                    cell[len(self.champions) + 1 + self.item_index[item]] += 1 / 3
        return result.reshape(-1)


def probabilities(features, parameters):
    hidden = np.tanh(features @ parameters["w1"] + parameters["b1"])
    logits = hidden @ parameters["w2"] + parameters["b2"]
    logits -= logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return hidden, exp / exp.sum(axis=1, keepdims=True)


class CombatValueModel:
    """Read only inference; no optimizer, provider API or arbitrary pickle loading."""

    def __init__(self, folder: Path, *, content_sha256: str, engine_sha256: str):
        folder = Path(folder)
        schema = json.loads((folder / "model-schema.json").read_text())
        if (
            schema.get("encoder_id") != ENCODER
            or schema.get("data_identity", {}).get("content_sha256") != content_sha256
            or schema.get("engine_sha256") != engine_sha256
        ):
            raise ValueError("Neural model encoder/content/simulator revision mismatch")
        path = folder / "candidate.npz"
        if path.stat().st_size > 32 * 1024**2:
            raise ValueError("Neural model exceeds memory budget")
        if hashlib.sha256(path.read_bytes()).hexdigest() != schema["checkpoint_sha256"]:
            raise ValueError("Neural model checksum mismatch")
        with zipfile.ZipFile(path) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 32 * 1024**2:
                raise ValueError("Neural tensors exceed memory budget")
        self.encoder = BoardEncoder(schema["champions"], schema["items"])
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != {"w1", "b1", "w2", "b2"}:
                raise ValueError("Unexpected neural parameter set")
            self.parameters = {key: archive[key] for key in archive.files}
        p = self.parameters
        width = p["b1"].size
        expected = {
            "w1": (self.encoder.size, width),
            "b1": (width,),
            "w2": (width, 3),
            "b2": (3,),
        }
        for name, value in p.items():
            if (
                value.shape != expected[name]
                or value.dtype != np.float32
                or not np.isfinite(value).all()
            ):
                raise ValueError("Invalid neural parameter shape/type/value")
            value.setflags(write=False)
        self.schema = schema

    def predict(self, team_pairs):
        if not 1 <= len(team_pairs) <= 512:
            raise ValueError("Predict requires 1..512 candidate fights")
        if any(
            u.stars not in self.schema["supported_stars"]
            for pair in team_pairs
            for p in pair
            for u in p.units
            if u.zone == "board"
        ):
            raise ValueError("Star level outside neural training scope")
        features = np.stack([self.encoder.encode(teams) for teams in team_pairs])
        _, values = probabilities(features, self.parameters)
        return values

    def value(self, teams):
        loss, _, win = self.predict([teams])[0]
        return float(win - loss)
