# Roadmap — Agente TFT

## Estado atual

### P0 — Fundação ✅

Implementado:

- contratos versionados `GameState`, `GameEvent`, `DecisionPacket`, `Recommendation`;
- Rust + Pydantic espelhados;
- CI Rust/Python;
- telemetria JSONL;
- PydanticAI-slim limitado à explicação;
- fallback determinístico de recomendação;
- perfis Ubuntu dev / Windows live target.

### P1 — Captura e Replay 🟡

Implementado:

- `CaptureSource`;
- `FrameEnvelope`;
- static fixtures;
- FFmpeg replay source;
- ROI normalizada;
- change detector por região;
- ROI router;
- replay inspector.

Falta para fechar o gate:

- benchmark em gravação real de TFT;
- perfis de ROI calibrados visualmente;
- metas de CPU/RAM/latência medidas;
- backend Windows entra posteriormente e não bloqueia o desenvolvimento no Ubuntu.

### P2 — HUD 🟡

Implementado:

- pré-processamento grayscale/contraste/threshold/upscale;
- interface `HudOcrEngine`;
- Tesseract backend;
- parser de stage/gold/HP/level/XP;
- domain gates;
- multi-pass OCR com supressão de ambiguidade;
- consenso temporal;
- `HudPipeline`;
- `hud-replay-inspect`.

Gate ainda não atingido:

- dataset real rotulado;
- layout real calibrado;
- precisão/recall por campo;
- taxa de unknown;
- teste de replay de uma partida completa.

### P3 — Shop / Board / Scouting 🟡

Implementado:

- matcher visual local por descriptors;
- separação explícita score visual × confidence;
- calibrador logístico offline;
- pipeline CommunityDragon → catálogo por set → assets locais;
- `perception-shop`;
- snapshot completo obrigatório;
- consenso temporal da shop;
- geometria de board/bench;
- contrato `BoardDetector`;
- associação de detecções a células;
- memória estabilizada de adversários;
- contestação por player/unidade;
- eventos `OpponentObserved` e `ContestationChanged`.

Gate ainda não atingido:

- templates/assets reais preparados para um set explícito;
- dataset de slots da loja rotulado;
- calibrador treinado em dados reais;
- detector ONNX de unidades;
- geometria real do board e bench;
- avaliação de scouting em replay.

### P4 — Items / Augments / Traits

- catálogo por patch;
- detector/classificador;
- confiança calibrada;
- associação item → unidade;
- regras de traits.

### P5 — TFT Math 🟡

Já implementado:

- economia/interest;
- shop odds configuráveis;
- pool snapshot;
- probabilidade de hit;
- budgets de roll;
- regras versionadas por patch/set;
- análise factual de contestação;
- `strategy-analysis` com janelas de 10/20/30g, probabilidade, expectativa e juros perdidos.

Falta:

- accounting completo do tier pool;
- cálculos de level/XP específicos por ruleset;
- board strength model;
- action feature vector.

### P6 — Coach determinístico 🟡

Já existe:

- `decision-core`;
- filtros de confiança;
- alternativas;
- evidence;
- fallback direto sem LLM.

Falta:

- produtores reais de candidate utilities;
- regras baseline reproduzíveis;
- comparação contra ações humanas em replay.

### P7 — Policy Model

- ambiente de treino;
- scripted opponents;
- imitation learning;
- PPO/self-play;
- opponent pool;
- avaliação contra baselines;
- export ONNX.

Gate: melhoria reproduzível contra baseline.

### P8 — PydanticAI-slim 🟡

Base já implementada:

- agent tipado;
- tools somente leitura/contexto;
- structured explanation;
- action/confidence imutáveis;
- fallback determinístico.

Falta:

- serviço local/IPC;
- timeout budget;
- escolha de modelo local/API;
- benchmark de latência;
- knowledge lookup patch-aware.

### P9 — UI lateral

- ação dominante;
- motivo curto;
- condição de parada;
- confiança;
- painel detalhado opcional;
- estado de percepção/unknown visível.

### P10 — Shadow Lab

- replay de partidas;
- agente vs ação humana;
- outcome tracking;
- dataset próprio;
- métricas por decisão;
- regressões.

## Regra de progressão

Nenhuma etapa é considerada concluída apenas porque o código existe.

Cada gate exige:

1. dados reais;
2. precisão/latência medidas;
3. testes reproduzíveis;
4. telemetria;
5. comportamento degradado explícito.

A prioridade permanece:

```text
estado confiável
→ fatos corretos
→ decisão
→ explicação curta
```
