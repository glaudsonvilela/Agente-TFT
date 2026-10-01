"""Storage guards and exported destinations; no model downloads or user disk mutation."""
import contextlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from training import board_detector_storage as storage

UUID = '12345678-1234-5678-9abc-123456789abc'
FREE = shutil._ntuple_diskusage(20*1024**3, 0, 20*1024**3)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base/'project'; self.project.mkdir()
        self.mount = self.base/'ssd'; self.mount.mkdir()
        self.root = self.mount/'Agente TFT'/'board3'
        self.env = dict(zip(storage.KEYS, [str(self.root), str(self.mount), UUID]))
        self.record = dict(target=str(self.mount), uuid=UUID, fstype='ext4', options='rw,noatime')

    @contextlib.contextmanager
    def mounted(self, record=None):
        with patch.object(storage, 'mount_record', return_value=record or self.record) as query, \
             patch.object(storage.shutil, 'disk_usage', return_value=FREE) as disk:
            yield query, disk

    def test_default_storage_unchanged(self):
        with patch.object(storage.shutil, 'disk_usage', return_value=FREE):
            exports, _, report = storage.prepare(self.project, {})
        self.assertEqual(exports['BOARD3_RUNTIME'], str(self.project/'telemetry/data/board3-runtime'))
        self.assertFalse(report['external'])

    def test_external_all_destinations_stay_on_ssd(self):
        with self.mounted():
            exports, _, report = storage.prepare(self.project, self.env)
        self.assertTrue(report['external'])
        for name, path in exports.items():
            if name.startswith(('BOARD3_', 'HF_', 'TORCH_', 'TRITON_', 'TMP')) or name in ('TEMP', 'PIP_CACHE_DIR', 'XDG_CACHE_HOME'):
                self.assertTrue(Path(path).is_relative_to(self.root), (name, path))
                self.assertTrue(Path(path).is_dir())
        self.assertFalse((self.project/'telemetry').exists())

    def test_full_system_partition_does_not_block_free_destination(self):
        def usage(p):
            self.assertTrue(Path(p).is_relative_to(self.mount))
            return FREE
        with self.mounted(), patch.object(storage.shutil, 'disk_usage', side_effect=usage):
            _, _, r = storage.prepare(self.project, self.env)
        self.assertEqual(r['destination_free_bytes'], FREE.free)

    def test_low_destination_space_fails_before_writes(self):
        low = shutil._ntuple_diskusage(10*1024**3, 9*1024**3, 1024**3)
        with self.mounted(), patch.object(storage.shutil, 'disk_usage', return_value=low), \
             self.assertRaisesRegex(ValueError, 'NO DESTINO'):
            storage.prepare(self.project, self.env)
        self.assertFalse(self.root.exists())

    def test_missing_mount_is_not_created(self):
        self.mount.rmdir()
        with self.assertRaisesRegex(ValueError, 'will NOT be created'):
            storage.prepare(self.project, self.env)
        self.assertFalse(self.mount.exists())

    def test_unmounted_directory_is_not_accepted(self):
        with patch.object(storage, 'mount_record', side_effect=ValueError('not mounted')), \
             self.assertRaises(ValueError):
            storage.prepare(self.project, self.env)
        self.assertFalse(self.root.exists())

    def test_wrong_uuid_rejected(self):
        with self.mounted(dict(self.record, uuid='00000000-0000-0000-0000-000000000000')), \
             self.assertRaisesRegex(ValueError, 'UUID mismatch'):
            storage.prepare(self.project, self.env)
        self.assertFalse(self.root.exists())

    def test_readonly_noexec_and_wrong_fs_rejected(self):
        for changes in [dict(options='ro'), dict(options='rw,noexec'), dict(fstype='ntfs')]:
            with self.subTest(changes=changes), self.mounted(dict(self.record, **changes)), self.assertRaises(ValueError):
                storage.prepare(self.project, self.env)
            self.assertFalse(self.root.exists())

    def test_partial_or_empty_external_configuration_rejected(self):
        for key in storage.KEYS:
            for value in [None, '']:
                env = self.env.copy()
                if value is None: env.pop(key)
                else: env[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'together'):
                    storage.prepare(self.project, env)
        self.assertFalse(self.root.exists())

    def test_outside_mount_or_mount_root_rejected(self):
        for value in [str(self.mount), str(self.base/'elsewhere')]:
            env = dict(self.env, TFT_BOARD3_STORAGE_ROOT=value)
            with self.assertRaisesRegex(ValueError, 'dedicated subdirectory'):
                storage.prepare(self.project, env)

    def test_symlink_destination_rejected(self):
        (self.mount/'Agente TFT').symlink_to(self.project, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symbolic links'):
            storage.prepare(self.project, self.env)
        self.assertFalse((self.project/'board3').exists())

    def test_cache_symlink_back_to_project_rejected(self):
        self.root.mkdir(parents=True)
        (self.root/'cache').symlink_to(self.project, target_is_directory=True)
        with self.mounted(), self.assertRaisesRegex(ValueError, 'symbolic links'):
            storage.prepare(self.project, self.env)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_nested_mount_rejected(self):
        def query(path, *, exact):
            return self.record if exact else dict(self.record, target=str(self.mount/'nested'))
        with self.mounted(), patch.object(storage, 'mount_record', side_effect=query), self.assertRaisesRegex(ValueError, 'another filesystem'):
            storage.prepare(self.project, self.env)
        self.assertFalse(self.root.exists())

    def test_rechecked_before_writes(self):
        exact_calls = 0
        def query(path, *, exact):
            nonlocal exact_calls
            if exact:
                exact_calls += 1
                if exact_calls == 2:
                    raise ValueError('SSD disconnected')
            return self.record
        with self.mounted(), patch.object(storage, 'mount_record', side_effect=query), self.assertRaisesRegex(ValueError, 'disconnected'):
            storage.prepare(self.project, self.env)
        self.assertFalse(self.root.exists())

    def test_repeat_preserves_existing_content(self):
        with self.mounted():
            first = storage.prepare(self.project, self.env)
            marker = self.root/'keep'; marker.write_bytes(b'do not remove')
            second = storage.prepare(self.project, self.env)
        self.assertEqual(first, second)
        self.assertEqual(marker.read_bytes(), b'do not remove')

    def test_runtime_link_cannot_relocate_an_existing_venv(self):
        self.root.mkdir(parents=True)
        runtime = self.root/'board3-runtime'; runtime.mkdir()
        (runtime/'venv').symlink_to(self.project, target_is_directory=True)
        with self.mounted(), self.assertRaisesRegex(ValueError, 'symbolic links'):
            storage.prepare(self.project, self.env)

    def test_shell_exports_quote_paths_and_redirect_tempfile(self):
        root = self.mount/"quoted ' ; touch UNWANTED ; #"/'board3'
        env = dict(self.env, TFT_BOARD3_STORAGE_ROOT=str(root))
        with self.mounted():
            exports, unset, _ = storage.prepare(self.project, env)
        code = "import os,tempfile,json; print(json.dumps([os.environ['PIP_CACHE_DIR'],tempfile.gettempdir(),os.environ.get('TRANSFORMERS_CACHE')]))"
        command = storage.shell_exports(exports, unset)+'\n'+shlex.quote(shutil.which('python3'))+' -B -c '+shlex.quote(code)
        clean = dict(os.environ, TRANSFORMERS_CACHE='/wrong/disk')
        r = subprocess.run(['bash', '-c', command], cwd=self.project, capture_output=True, text=True, env=clean, check=True)
        self.assertEqual(json.loads(r.stdout), [str(root/'cache/pip'), str(root/'tmp'), None])
        self.assertFalse((self.project/'UNWANTED').exists())
        self.assertFalse(list(self.project.rglob('__pycache__')))

    def test_real_mount_query_parses_json_without_creating_paths(self):
        if not shutil.which('findmnt'):
            self.skipTest('findmnt unavailable')
        record = storage.mount_record(Path('/'), exact=True)
        self.assertEqual(record['target'], '/')
        self.assertIsInstance(record['options'], str)

    def test_mount_query_error_and_duplicate_rows(self):
        for result in [subprocess.CompletedProcess([], 1, '', ''),
                       subprocess.CompletedProcess([], 0, '{"filesystems":[{},{}]}', '')]:
            with patch.object(storage.subprocess, 'run', return_value=result), self.assertRaises(ValueError):
                storage.mount_record(self.mount, exact=True)

    def test_launchers_share_storage_and_do_not_recompile(self):
        root = Path(__file__).resolve().parents[2]
        runner = (root/'scripts/probe_match001_board_detector.sh').read_text()
        setup = (root/'scripts/setup_board_detector.sh').read_text()
        self.assertIn('source "$ROOT/scripts/board_detector_storage.sh"', runner)
        self.assertIn('source "$ROOT/scripts/board_detector_storage.sh"', setup)
        self.assertIn('VENV="$BOARD3_RUNTIME/venv"', setup)
        self.assertIn('MODEL="$BOARD3_MODEL_CACHE"', runner)
        self.assertIn('mktemp -d "$BOARD3_STORAGE_ROOT/', runner)
        self.assertNotIn('cargo build', runner)
        self.assertNotIn('shutil.disk_usage(sys.argv[1])', runner)
        self.assertIn('available<3*1024**3', runner)
        for text in [runner, setup]:
            self.assertNotIn('rm -rf', text)
            self.assertNotIn('sudo', text)


if __name__ == '__main__':
    unittest.main()
