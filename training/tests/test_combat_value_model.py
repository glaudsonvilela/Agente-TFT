"""Inference checks identity, supported input and immutable numeric weights."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from trainer.simulation.state import Player, Unit
from trainer.simulation.value_model import BoardEncoder, CombatValueModel, ENCODER


class CombatValueModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        encoder = BoardEncoder(["unit"], ["rod"])
        rng = np.random.default_rng(4)
        self.parameters = {
            "w1": rng.normal(0, 0.1, (encoder.size, 4)).astype("float32"),
            "b1": np.zeros(4, dtype="float32"),
            "w2": rng.normal(0, 0.1, (4, 3)).astype("float32"),
            "b2": np.zeros(3, dtype="float32"),
        }
        self.schema = dict(
            encoder_id=ENCODER,
            data_identity={"content_sha256": "content"},
            engine_sha256="engine",
            champions=["unit"],
            items=["rod"],
            supported_stars=[1, 2],
        )
        self.save()
        self.teams = [
            Player(
                0,
                1,
                0,
                units=[
                    Unit("a", "unit", zone="board", position=(0, 0)),
                ],
            ),
            Player(0, 1, 0),
        ]

    def save(self):
        checkpoint = self.folder / "candidate.npz"
        np.savez_compressed(checkpoint, **self.parameters)
        self.schema["checkpoint_sha256"] = hashlib.sha256(
            checkpoint.read_bytes()
        ).hexdigest()
        (self.folder / "model-schema.json").write_text(json.dumps(self.schema))

    def load(self, **identities):
        return CombatValueModel(
            self.folder,
            **dict(
                {"content_sha256": "content", "engine_sha256": "engine"}, **identities
            )
        )

    def test_batch_and_single_predictions_agree_without_mutating_parameters(self):
        model = self.load()
        single = model.predict([self.teams])[0]
        batch = model.predict([self.teams, self.teams])
        np.testing.assert_allclose(batch, np.stack([single, single]))
        np.testing.assert_allclose(batch.sum(axis=1), 1, atol=np.finfo(np.float32).eps)
        for name, tensor in model.parameters.items():
            self.assertFalse(tensor.flags.writeable)
            np.testing.assert_array_equal(tensor, self.parameters[name])

    def test_content_or_engine_changes_require_a_matching_model(self):
        for identity in ("content_sha256", "engine_sha256"):
            with self.subTest(identity=identity), self.assertRaisesRegex(
                ValueError, "revision mismatch"
            ):
                self.load(**{identity: "changed"})

    def test_corrupted_checkpoint_is_rejected_before_loading(self):
        with (self.folder / "candidate.npz").open("ab") as file:
            file.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.load()

    def test_invalid_tensors_are_rejected_even_with_matching_checksum(self):
        for tensor in (
            np.zeros((4, 4), dtype="float32"),
            np.full((4, 3), np.nan, dtype="float32"),
            np.zeros((4, 3), dtype="float64"),
        ):
            with self.subTest(shape=tensor.shape, dtype=tensor.dtype):
                self.parameters["w2"] = tensor
                self.save()
                with self.assertRaisesRegex(ValueError, "shape/type/value"):
                    self.load()

    def test_untrained_stars_and_hidden_permanent_effects_are_not_ignored(self):
        model = self.load()
        self.teams[0].units[0].stars = 3
        with self.assertRaisesRegex(ValueError, "Star level"):
            model.predict([self.teams])
        self.teams[0].units[0].stars = 1
        self.teams[0].units[0].permanent = {"damage": 10}
        with self.assertRaisesRegex(ValueError, "Permanent"):
            model.predict([self.teams])


if __name__ == "__main__":
    unittest.main()
