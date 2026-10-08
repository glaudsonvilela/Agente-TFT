"""Run the installed studio flow against an explicitly selected Ubuntu X11 monitor.

The replay is played in any normal video player. This launcher only stages
small links to the existing model, native readers, UI, and patch catalog.
"""
from pathlib import Path
import argparse
import json
import os
import sys
from prepare_tessdata_best import prepare as prepare_ocr_model


REPO = Path(__file__).resolve().parents[1]
SSD = Path('/mnt/sherlock-ssd/AgenteTFT')
DEFAULT_MODEL_DIR = SSD / 'diagnostics/bigbanana-neural-bundle-20261007-1535/runtime-seed/models'
DEFAULT_HP = SSD / 'build-targets/hm-hp-native/release/agente-tft-hm-hp'
DEFAULT_ITEM_ASSETS = (REPO / 'build/hm4-live-assets'
                       if (REPO / 'build/hm4-live-assets/ASSET_REPORT.json').is_file()
                       else SSD / 'work/Agente-TFT/build/hm4-live-assets')
DEFAULT_ITEM_NATIVE = REPO / 'tools/hm-item-native/target/release/libagente_tft_hm_item_native.so'
DEFAULT_WORKER = (Path(os.environ['CARGO_TARGET_DIR']) if os.environ.get('CARGO_TARGET_DIR')
                  else REPO / 'tools/e1-native/target') / 'release/agente-tft-e1-worker'


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


def prepare(stage: Path, model_dir: Path, worker: Path, hp_worker: Path,
            item_assets: Path, item_native: Path):
    stage.mkdir(parents=True, exist_ok=True)
    visual = json.loads((REPO / 'configs/catalog/active-visual-reference-v1.json').read_text())
    reference = json.loads((REPO / visual['reference'] / 'reference.json').read_text())
    report = json.loads((item_assets / 'ASSET_REPORT.json').read_text())
    if (report.get('reference_sha256') != reference.get('reference_sha256')
            or report.get('set_key') != visual['set_key']
            or not (item_assets / visual['icon_dir']).is_dir()):
        raise ValueError('Galeria de itens não corresponde ao catálogo ativo.')
    link(REPO / 'configs', stage / 'configs')
    link(REPO / 'knowledge', stage / 'knowledge')
    link(REPO / 'ui', stage / 'ui')
    link(model_dir, stage / 'models')
    link(worker, stage / 'bin/agente-tft-e1-worker')
    link(hp_worker, stage / 'bin/agente-tft-hm-hp')
    link(item_native, stage / 'bin/libagente_tft_hm_item_native.so')
    link(item_assets / visual['icon_dir'], stage / visual['icon_dir'])
    if not (stage / 'models/deployment-candidate.json').is_file():
        raise FileNotFoundError('Metadados do modelo visual ausentes.')
    return stage


def main(argv=None):
    parser = argparse.ArgumentParser(description='Agente TFT: laboratório ao vivo no Ubuntu X11')
    parser.add_argument('--stage', type=Path, default=SSD / 'diagnostics/ubuntu-live-mvp')
    parser.add_argument('--model-dir', type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument('--neural-bundle', type=Path,
                        help='Pacote visual completo já instalado no SSD para o laboratório Ubuntu.')
    parser.add_argument('--worker', type=Path,
                        default=DEFAULT_WORKER)
    parser.add_argument('--hp-worker', type=Path, default=DEFAULT_HP)
    parser.add_argument('--item-assets', type=Path, default=DEFAULT_ITEM_ASSETS)
    parser.add_argument('--item-native', type=Path, default=DEFAULT_ITEM_NATIVE)
    parser.add_argument('--no-browser', action='store_true',
                        help='Serve o estúdio sem abrir uma segunda janela de navegador.')
    args = parser.parse_args(argv)
    if os.environ.get('XDG_SESSION_TYPE') != 'x11' or not os.environ.get('DISPLAY'):
        parser.error('Entre no Ubuntu usando a sessão Xorg para capturar o monitor.')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    venv_python = next((candidate for candidate in (
        args.stage.resolve() / '.venv/bin/python',
        SSD / 'simulator-lab/build-cache/venv/bin/python') if candidate.is_file()), None)
    if venv_python and Path(sys.prefix) != venv_python.parent.parent:
        os.execv(str(venv_python), [str(venv_python), __file__, *(argv or sys.argv[1:])])
    model_dir = args.neural_bundle / 'models' if args.neural_bundle else args.model_dir
    stage = prepare(args.stage.resolve(), model_dir.resolve(),
                    args.worker.resolve(), args.hp_worker.resolve(),
                    args.item_assets.resolve(), args.item_native.resolve())
    os.environ['TESSDATA_PREFIX'] = str(prepare_ocr_model())
    os.environ['AGENTE_TFT_UBUNTU_MVP'] = '1'
    if args.neural_bundle:
        os.environ['AGENTE_TFT_UBUNTU_NEURAL_BUNDLE'] = str(args.neural_bundle.resolve())
    os.environ['AGENTE_TFT_MODEL'] = str(stage / 'models/deployment-candidate.json')
    os.environ['LOCALAPPDATA'] = str(stage / 'local-data')
    sys._MEIPASS = str(stage)
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / 'apps/hud_mapper'))
    sys.path.insert(0, str(REPO / 'apps/e1_replay'))
    from hm.studio_bridge import run_studio
    print('Agente TFT Ubuntu MVP: selecione o monitor em que o vídeo está rodando.', flush=True)
    print(f'Registros da sessão: {stage / "local-data/AgenteTFT-HUD-HM4/sessions"}', flush=True)
    return run_studio(browser=not args.no_browser)


if __name__ == '__main__':
    raise SystemExit(main())
