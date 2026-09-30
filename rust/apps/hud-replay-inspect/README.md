# hud-replay-inspect

Executa o pipeline HUD completo sobre uma gravação de TFT:

```text
video
 ↓
FFmpeg
 ↓
FrameEnvelope
 ↓
HudLayout
 ↓
ROI extraction
 ↓
preprocess variants
 ↓
Tesseract
 ↓
domain validation
 ↓
temporal consensus
 ↓
GameState + GameEvents
```

## Uso

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-hud-replay-inspect -- \
  partida.mp4 hud-layout.json 5 1800
```

A ferramenta só imprime updates quando o `GameState` muda ou quando há eventos semânticos.

O layout deve ser calibrado contra uma captura real. Não há coordenadas inventadas no repositório.
