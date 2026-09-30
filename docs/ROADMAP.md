# Roadmap — Agente TFT

## P0 — Fundação

- repository layout;
- schemas de GameState;
- schemas de Recommendation;
- event taxonomy;
- telemetria;
- perfis lab/replay/live-approved.

**Gate:** contratos versionados e testes básicos.

## P1 — Captura e calibração

- detectar janela/resolução;
- definir ROIs;
- captura eficiente;
- frame timestamps;
- benchmark CPU/RAM.

**Gate:** captura estável por uma partida inteira.

## P2 — Percepção HUD

- round;
- HP;
- gold;
- level;
- XP;
- detecção de transições.

**Gate:** alta precisão em dataset de replay.

## P3 — Shop / Bench / Board

- reconhecimento de unidades;
- estrelas;
- posições;
- tracking temporal;
- confidence model.

**Gate:** GameState reconstruído de forma consistente.

## P4 — Items / Augments / Traits

- reconhecimento;
- Knowledge Pack;
- validação por patch.

## P5 — TFT Math

- economia;
- shop odds;
- level;
- pool/contestação observada;
- candidatos de ação.

**Gate:** cálculos testados independentemente da IA.

## P6 — Coach determinístico

Antes de policy model, produzir recomendações simples por regras e scores.

Objetivo: validar UI, contratos e telemetria.

## P7 — Policy Model

- ambiente de treino;
- scripted opponents;
- imitation learning;
- PPO/self-play;
- avaliação contra baselines;
- export ONNX.

**Gate:** melhoria mensurável e reproduzível contra baseline.

## P8 — PydanticAI-slim

- toolset;
- structured outputs;
- explanation layer;
- conflict resolution;
- timeouts/fallbacks.

## P9 — UI lateral

- ação dominante;
- motivo curto;
- condição de parada;
- confiança;
- painel expandido opcional.

## P10 — Shadow Lab

- replay de partidas;
- comparação agente vs jogador;
- outcome tracking;
- dataset proprietário;
- regressões.

## Regra de progressão

Não avançar de percepção para estratégia enquanto o GameState não tiver confiabilidade mensurada. Não avançar de estratégia para treino pesado enquanto os cálculos determinísticos não estiverem validados.
