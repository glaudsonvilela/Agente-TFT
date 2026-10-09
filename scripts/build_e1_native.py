"""Build the exact Rust worker loaded by the local HUD runtime."""

from pathlib import Path
import os
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    worker = root / 'tools/e1-native/target/release' / (
        'agente-tft-e1-worker.exe' if os.name == 'nt' else 'agente-tft-e1-worker')
    # The SSD development setup links this path to a shared Cargo target dir.
    # A plain cargo build can otherwise leave the live worker unchanged.
    target_dir = worker.resolve().parent.parent if worker.is_symlink() else worker.parent.parent
    env = dict(os.environ, CARGO_TARGET_DIR=str(target_dir))
    subprocess.run(['cargo', 'build', '--release', '--manifest-path',
                    str(root / 'tools/e1-native/Cargo.toml')],
                   cwd=root, env=env, check=True)
    if not worker.is_file():
        raise SystemExit(f'Runtime worker missing after build: {worker}')
    print(f'Runtime worker updated: {worker.resolve()}')


if __name__ == '__main__':
    main()
