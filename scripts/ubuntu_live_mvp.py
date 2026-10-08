"""Run the installed studio flow against an explicitly selected Ubuntu X11 monitor.

The replay is played in any normal video player. This launcher only stages
small links to the existing model, native readers, UI, and patch catalog.
"""
from pathlib import Path
import argparse
import os
import sys


REPO = Path(__file__).resolve().parents[1]
SSD = Path('/mnt/sherlock-ssd/AgenteTFT')
DEFAULT_MODEL_DIR = SSD / 'diagnostics/bigbanana-neural-bundle-20261007-1535/runtime-seed/models'
DEFAULT_HP = SSD / 'build-targets/hm-hp-native/release/agente-tft-hm-hp'


def link(target: Path, location: Path):
    if not target.exists():
        raise FileNotFoundError(f'Componente do MVP ausente: {target}')
    location.parent.mkdir(parents=True, exist_ok=True)
    if location.is_symlink():
        if location.resolve() == target.resolve():
            return
        location.unlink()
    elif location.exists():
        raise FileExistsError(f'Pasta do MVP já contém outro arquivo: {location}')
    location.symlink_to(target, target_is_directory=target.is_dir())


def prepare(stage: Path, model_dir: Path, worker: Path, hp_worker: Path):
    stage.mkdir(parents=True, exist_ok=True)
    link(REPO / 'configs', stage / 'configs')
    link(REPO / 'knowledge', stage / 'knowledge')
    link(REPO / 'ui', stage / 'ui')
    link(model_dir, stage / 'models')
    link(worker, stage / 'bin/agente-tft-e1-worker')
    link(hp_worker, stage / 'bin/agente-tft-hm-hp')
    if not (stage / 'models/deployment-candidate.json').is_file():
        raise FileNotFoundError('Metadados do modelo visual ausentes.')
    return stage


def main(argv=None):
    parser = argparse.ArgumentParser(description='Agente TFT: laboratório ao vivo no Ubuntu X11')
    parser.add_argument('--stage', type=Path, default=SSD / 'diagnostics/ubuntu-live-mvp')
    parser.add_argument('--model-dir', type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument('--worker', type=Path,
                        default=REPO / 'tools/e1-native/target/release/agente-tft-e1-worker')
    parser.add_argument('--hp-worker', type=Path, default=DEFAULT_HP)
    args = parser.parse_args(argv)
    if os.environ.get('XDG_SESSION_TYPE') != 'x11' or not os.environ.get('DISPLAY'):
        parser.error('Entre no Ubuntu usando a sessão Xorg para capturar o monitor.')
    venv_python = args.stage.resolve() / '.venv/bin/python'
    if venv_python.is_file() and Path(sys.prefix) != venv_python.parent.parent:
        os.execv(str(venv_python), [str(venv_python), __file__, *(argv or sys.argv[1:])])
    stage = prepare(args.stage.resolve(), args.model_dir.resolve(),
                    args.worker.resolve(), args.hp_worker.resolve())
    os.environ['AGENTE_TFT_UBUNTU_MVP'] = '1'
    os.environ['AGENTE_TFT_MODEL'] = str(stage / 'models/deployment-candidate.json')
    os.environ['LOCALAPPDATA'] = str(stage / 'local-data')
    sys._MEIPASS = str(stage)
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / 'apps/hud_mapper'))
    sys.path.insert(0, str(REPO / 'apps/e1_replay'))
    from hm.studio_bridge import run_studio
    print('Agente TFT Ubuntu MVP: selecione o monitor em que o vídeo está rodando.', flush=True)
    print(f'Registros da sessão: {stage / "local-data/AgenteTFT-HUD-HM4/sessions"}', flush=True)
    return run_studio(browser=True)


if __name__ == '__main__':
    raise SystemExit(main())
