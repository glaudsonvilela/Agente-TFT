import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import numpy as np
from PIL import Image
import pytest

from training.simulator_lab.catalog_sessions import SessionSource, catalog, safe_relative
from training.simulator_lab.selfplay import gae, run
from remote_trainer.policy_learning import policy_learning_jobs


def test_gae_bootstraps_live_player_but_never_a_terminal():
    advantages, returns = gae([0, 1], [.1, .2], [False, True], 999, gamma=.5, lam=1)
    assert np.allclose(returns, [.5, 1])
    assert np.allclose(advantages, [.4, .8])
    _, live_returns = gae([0, 0], [0, 0], [False, False], 4, gamma=.5, lam=1)
    assert np.allclose(live_returns, [1, 2])


def test_current_patch_cannot_silently_use_wrong_set(tmp_path):
    with pytest.raises(ValueError, match='Set18 training blocked'):
        run(SimpleNamespace(profile='current-patch', output=tmp_path/'job'))
    assert not (tmp_path/'job').exists()


def session_fixture(root):
    root.mkdir()
    image = Image.new('RGB', (8, 8), (32, 64, 128))
    stream = io.BytesIO(); image.save(stream, format='PNG')
    data = stream.getvalue()
    (root/'frame.png').write_bytes(data)
    manifest = dict(session_id=root.name, samples=[dict(image='frame.png', width=8, height=8,
        image_sha256=hashlib.sha256(data).hexdigest(),
        decoded_rgb_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
        targets={'champion':'UNVERIFIED_PREDICTION'})])
    (root/'training-manifest.json').write_text(json.dumps(manifest))
    return manifest, data


def test_catalog_deduplicates_pixels_without_creating_labels(tmp_path):
    first, second = tmp_path/'one', tmp_path/'two'
    session_fixture(first); session_fixture(second)
    output = tmp_path/'index.json'
    result = catalog([first, second], output)
    assert result['unique_frames'] == 1
    assert result['duplicate_frames'] == 1
    assert result['reviewed_labels'] == 0
    frame = json.loads(output.read_text())['frames'][0]
    assert len(frame['observations']) == 2
    assert frame['split'] == 'unassigned'
    assert frame['labels'] == {}
    assert frame['seasonal_binding'] is None


def test_catalog_rejects_tampered_frame(tmp_path):
    root = tmp_path/'session'; session_fixture(root)
    (root/'frame.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        catalog([root], tmp_path/'index.json')
    assert not (tmp_path/'index.json').exists()


def test_conflicting_zip_entries_are_not_silently_selected(tmp_path):
    root = tmp_path/'session'
    manifest, data = session_fixture(root)
    archive = tmp_path/'session.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('session/training-manifest.json', json.dumps(manifest))
        z.writestr('session/frame.png', data)
        with pytest.warns(UserWarning):
            z.writestr('session/frame.png', b'wrong')
    with pytest.raises(ValueError, match='Conflicting duplicate'):
        catalog([archive], tmp_path/'index.json')


@pytest.mark.parametrize('path', ['../secret', '/etc/passwd', 'C:\\secret', 'samples/../../secret'])
def test_unsafe_archive_paths_rejected(path):
    with pytest.raises(ValueError):
        safe_relative(path)


def test_policy_dashboard_cannot_claim_real_training_and_verifies_hash(tmp_path):
    folder = tmp_path/'policy-runs'/'test'; folder.mkdir(parents=True)
    (folder/'progress.json').write_text(json.dumps(dict(kind='policy_selfplay',
        runtime_promoted=False, current_patch_training_ready=True, status='completed',
        matches_completed=3, transitions=50)))
    checkpoint = folder/'checkpoint-000001.pt'; checkpoint.write_bytes(b'not executed')
    (folder/'checkpoint.json').write_text(json.dumps(dict(path=checkpoint.name,
        sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())))
    job = policy_learning_jobs(tmp_path/'trainer.sqlite')[0]
    assert job['checkpoint_verified'] is True
    assert job['current_patch_training_ready'] is False
    assert job['matches_completed'] == 3
    checkpoint.write_bytes(b'tampered')
    assert policy_learning_jobs(tmp_path/'trainer.sqlite')[0]['checkpoint_verified'] is False
