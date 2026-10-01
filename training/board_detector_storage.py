"""B3 storage routing only. Never mount, move, delete user data or weaken B1 checks."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

MIN_FREE = 4 * 1024**3
KEYS = ('TFT_BOARD3_STORAGE_ROOT', 'TFT_BOARD3_STORAGE_MOUNT', 'TFT_BOARD3_STORAGE_UUID')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def absolute_path(value):
    require(isinstance(value, str) and value and not any(c in value for c in '\x00\n\r'),
            'invalid storage path')
    p = Path(value)
    require(p.is_absolute() and '..' not in p.parts, 'storage paths must be absolute without ..')
    require(p.resolve(strict=False) == p, 'storage paths must not traverse symbolic links: '+str(p))
    return p


def nearest_existing(path):
    p = path
    while not p.exists():
        require(not p.is_symlink(), 'dangling storage symlink: '+str(p))
        p = p.parent
    require(p.is_dir(), 'storage parent is not a directory: '+str(p))
    return p


def mount_record(path, *, exact):
    cmd = ['findmnt', '--json', '--first-only', '--mountpoint' if exact else '--target',
           str(path), '--output', 'TARGET,UUID,FSTYPE,OPTIONS']
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    require(result.returncode == 0, 'SSD not mounted at the required location: '+str(path))
    rows = json.loads(result.stdout).get('filesystems', [])
    require(len(rows) == 1, 'ambiguous mounted filesystem')
    return rows[0]


def validate_mount(mount, expected_uuid):
    require(mount.is_dir(), 'required mountpoint missing; it will NOT be created')
    actual = mount_record(mount, exact=True)
    require(actual.get('target') == str(mount), 'mountpoint does not match exactly')
    require(str(actual.get('uuid', '')).lower() == expected_uuid, 'SSD UUID mismatch; no writes')
    options = set(actual.get('options', '').split(','))
    require('rw' in options and 'ro' not in options, 'SSD must be mounted read/write')
    require('noexec' not in options, 'SSD is noexec; virtual environment cannot run here')
    require(actual.get('fstype') in ('ext4', 'ext3', 'ext2', 'xfs', 'btrfs'),
            'SSD filesystem must support Unix executables and symbolic links')
    return actual


def paths_for(root):
    return {
        'BOARD3_STORAGE_ROOT': root,
        'BOARD3_RUNTIME': root/'board3-runtime',
        'BOARD3_MODEL_CACHE': root/'board3-models',
        'TMPDIR': root/'tmp', 'TEMP': root/'tmp', 'TMP': root/'tmp',
        'XDG_CACHE_HOME': root/'cache',
        'PIP_CACHE_DIR': root/'cache/pip',
        'HF_HOME': root/'cache/huggingface',
        'HF_HUB_CACHE': root/'cache/huggingface/hub',
        'HF_ASSETS_CACHE': root/'cache/huggingface/assets',
        'HF_XET_CACHE': root/'cache/huggingface/xet',
        'TORCH_HOME': root/'cache/torch',
        'TORCH_EXTENSIONS_DIR': root/'cache/torch-extensions',
        'TRITON_CACHE_DIR': root/'cache/triton',
    }


def prepare(project, env=None):
    env = os.environ if env is None else env
    project = Path(project).resolve(strict=True)
    require(project.is_dir(), 'project directory missing')
    supplied = [k in env for k in KEYS]
    external = any(supplied)
    mount = None
    expected_uuid = None
    if external:
        require(all(supplied) and all(env[k] for k in KEYS),
                'external storage requires ROOT, MOUNT and UUID together; no fallback')
        root, mount = (absolute_path(env[k]) for k in KEYS[:2])
        expected_uuid = str(uuid.UUID(env[KEYS[2]]))
        require(mount != Path('/') and root != mount and root.is_relative_to(mount),
                'storage must be a dedicated subdirectory of the SSD mountpoint')
        validate_mount(mount, expected_uuid)
    else:
        root = absolute_path(str(project/'telemetry/data'))

    paths = paths_for(root)
    # Validate every destination before creating any directory. Do not follow a
    # cache/runtime symlink back to the already-full system partition.
    checked = list(dict.fromkeys(paths.values())) + [root/'board3-runtime/venv']
    for p in checked:
        absolute_path(str(p))
        parent = nearest_existing(p)
        if external:
            actual = mount_record(parent, exact=False)
            require(actual.get('target') == str(mount)
                    and str(actual.get('uuid', '')).lower() == expected_uuid,
                    'storage path is on another filesystem/mount: '+str(p))
    free = shutil.disk_usage(nearest_existing(root)).free
    require(free >= MIN_FREE, 'B3 precisa de 4 GiB livres NO DESTINO: '+str(root))

    # Recheck immediately before writes; never create /mnt/... as a substitute
    # for a disconnected SSD. This is not a guarantee against forced hot unplug.
    if external:
        validate_mount(mount, expected_uuid)
    for p in dict.fromkeys(paths.values()):
        p.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in (root/'board3-runtime/setup.lock', root/'board3-runtime/run.lock',
              root/'board3-runtime/requirements.sha256'):
        require(not p.is_symlink(), 'storage control file must not be a symlink: '+str(p))
    try:
        with tempfile.TemporaryFile(dir=paths['TMPDIR']) as f:
            f.write(b'board3-storage-check\n')
            f.flush()
    except OSError as e:
        raise ValueError('storage is not writable by the current user: '+str(root)) from e
    exports = {k: str(v) for k, v in paths.items()}
    exports.update(PYTHONDONTWRITEBYTECODE='1', PIP_CONFIG_FILE=os.devnull,
                   PIP_DISABLE_PIP_VERSION_CHECK='1')
    # Deprecated variables can override HF_HOME or point pip to an unrelated log.
    unset = ['PYTHONPYCACHEPREFIX', 'TRANSFORMERS_CACHE', 'PYTORCH_TRANSFORMERS_CACHE',
             'PYTORCH_PRETRAINED_BERT_CACHE', 'HUGGINGFACE_HUB_CACHE', 'PIP_LOG',
             'PIP_TARGET', 'PIP_PREFIX', 'PIP_USER']
    report = dict(schema_version=1, policy='b3_storage_routing_v1', external=external,
                  root=str(root), mountpoint=str(mount) if mount else None,
                  expected_uuid=expected_uuid, destination_free_bytes=free,
                  minimum_free_bytes=MIN_FREE, paths=exports,
                  project_moved=False, baseline_moved=False, user_files_deleted=False)
    return exports, unset, report


def shell_exports(exports, unset):
    return '\n'.join(['unset '+k for k in unset] +
                     ['export '+k+'='+shlex.quote(v) for k, v in exports.items()])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--shell', action='store_true')
    args = parser.parse_args()
    try:
        exports, unset, report = prepare(args.project)
        message = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if args.shell:
            exports['BOARD3_STORAGE_JSON'] = message
            print(shell_exports(exports, unset))
            print('BOARD3_STORAGE='+message, file=sys.stderr)
        else:
            print(message)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as e:
        parser.exit(2, 'BOARD3_STORAGE_ERROR='+str(e)+'\n')


if __name__ == '__main__':
    main()
