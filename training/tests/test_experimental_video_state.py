import json

import numpy as np
import pytest
import torch

from training.experimental_video_state import StateNet, load_examples, numeric_state
from training.package_experimental_video_state_akash import package


def test_unknown_ocr_stays_unknown():
    values, valid = numeric_state({"parsed": {"stage": "2-3", "gold": None,
                                                "level": 5}})
    assert np.array_equal(valid, np.array([1, 0, 1], dtype=np.float32))
    assert values.tolist() == pytest.approx([10 / 70, 0, 0.5])


def test_whole_vod_is_held_out(tmp_path):
    matches = []
    for vod in ("2897329575", "2894958056"):
        match_id = f"setsuko-{vod}-game1"
        folder = tmp_path / match_id
        folder.mkdir()
        observations = []
        for number in range(1, 5):
            filename = f"frame-{number:06d}.jpg"
            (folder / filename).touch()
            observations.append({"frame_number": number, "frame": filename,
                                 "parsed": {"stage": "2-1", "gold": 20,
                                            "level": 4}})
        matches.append({"match_id": match_id, "source_vod_id": vod,
                        "observations": observations})
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"schema_version": 1, "interval_seconds": 15,
                                 "native_resolution": [1920, 1080],
                                 "matches": matches}))
    train, holdout = load_examples(index, tmp_path, "2894958056")
    assert len(train) == len(holdout) == 2
    assert {row["match_id"] for row in train} == {"setsuko-2897329575-game1"}
    assert {row["match_id"] for row in holdout} == {"setsuko-2894958056-game1"}


def test_initial_network_equals_persistence_baseline():
    model = StateNet().eval()
    state = torch.tensor([[0.23, 0.35, 0.5, 1, 1, 1]], dtype=torch.float32)
    with torch.no_grad():
        output = model(torch.zeros((1, 3, 180, 320)), state)
    assert torch.equal(output[0], state[0, :3])


def test_sparse_package_cannot_be_launched_as_imitation_by_default(tmp_path):
    with pytest.raises(ValueError, match="cannot train imitation/player policy"):
        package(tmp_path, tmp_path, tmp_path / "index.json",
                tmp_path / "output", tmp_path / "branches.json")
    assert not (tmp_path / "output").exists()
