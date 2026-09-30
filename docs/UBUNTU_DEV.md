# Desenvolvimento no Ubuntu

O Ubuntu é o ambiente principal de desenvolvimento do Agente TFT.

## O que pode ser desenvolvido aqui

- core Rust;
- contratos;
- replay de partidas;
- visão/OCR;
- Knowledge Pack;
- Riot/Data Dragon/CommunityDragon ingestion;
- TFT Math;
- simulador/self-play;
- PyTorch;
- export ONNX;
- PydanticAI-slim;
- UI;
- telemetria;
- testes de regressão.

A captura live do cliente TFT será validada posteriormente no Windows.

## Dependências atuais

```bash
sudo apt-get update
sudo apt-get install -y build-essential ffmpeg python3 python3-venv python3-pip
```

Rust deve estar instalado pelo `rustup`.

## Testar o core Rust

```bash
cargo test --manifest-path rust/Cargo.toml
```

## Testar os contratos Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "pydantic>=2.8,<3" "pytest>=8,<9"
cd agent
python -m pytest -q
```

## Replay

O backend de replay usa FFmpeg:

```text
vídeo TFT
   ↓
ffprobe → resolução / FPS
   ↓
ffmpeg → RGBA
   ↓
FrameEnvelope
   ↓
ROI router
   ↓
somente regiões alteradas
```

O vídeo original não é modificado.

## Regra de dados grandes

Vídeos, capturas, datasets e modelos não entram no Git normal. Eles ficam em diretórios ignorados ou, futuramente, em armazenamento de artefatos/versionamento específico.

## Inspecionar um vídeo de TFT

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-replay-inspect -- \
  partida.mp4 10 600
```

Isso valida o caminho `vídeo → FFmpeg → FrameEnvelope` e imprime metadados/timestamps em JSON.
