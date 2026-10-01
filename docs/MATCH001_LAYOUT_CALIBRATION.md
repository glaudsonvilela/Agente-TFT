# Match 001 — calibração de layout 1920×1080

Fonte real:

- replay: `TFT_MATCH_001.mp4`
- resolução: 1920×1080
- FPS de origem: 60
- duração: ~32m39s
- frames estratégicos extraídos: 40
- primeira fixture visual usada para traçar as regiões: planning/shop + scouting do mesmo replay

## Descoberta importante: HP não é ROI fixa

A lista de jogadores à direita reordena conforme o estado do lobby. A própria linha do jogador local aparece em alturas diferentes ao longo da partida.

Por isso:

- `stage`, `gold`, `level` e `xp` usam ROIs estáticas;
- `hp` **não** entra no `HudLayout` estático;
- HP deverá ser lido a partir de `player_list`, identificando dinamicamente a linha local.

Isso evita atrelar HP a uma coordenada que deixa de apontar para o jogador quando a classificação muda.

## Perfis

### ROI change detector

`configs/roi/tft-1920x1080-match001-v1.json`

Inclui:

- stage
- gold
- level_xp
- shop
- bench
- board
- items
- player_list

`augments` ficou de fora deste primeiro perfil porque os 40 frames amostrados não capturaram uma tela de escolha com qualidade suficiente para congelar coordenadas sem inventar.

### HUD OCR

`configs/hud/tft-1920x1080-match001-v1.json`

Inclui apenas campos realmente estáticos no replay:

- stage
- gold
- level
- xp

HP será adicionado ao pipeline por leitura dinâmica de `player_list`.

## Próximo teste no replay inteiro

### Change detector

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-roi-replay-inspect -- \
  telemetry/replays/match-001/TFT_MATCH_001.mp4 \
  configs/roi/tft-1920x1080-match001-v1.json \
  5 \
  9800
```

A saída JSONL deve mostrar eventos nas regiões certas conforme shop/board/player list mudam.

### HUD OCR

Requer `tesseract`.

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-hud-replay-inspect -- \
  telemetry/replays/match-001/TFT_MATCH_001.mp4 \
  configs/hud/tft-1920x1080-match001-v1.json \
  5 \
  9800
```

Primeiro objetivo: validar `stage/gold/level/xp` contra os frames já pré-anotados.

## Regra

Esses perfis foram derivados de uma fixture real 1920×1080. Eles são baseline v1, não uma promessa de generalização para outras resoluções, escala de UI, patches ou layouts.
