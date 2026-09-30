# FIRST REAL REPLAY — Agente TFT

Objetivo: transformar uma gravação real de TFT em um primeiro benchmark objetivo de percepção + Opportunity Engine.

## 1. Gravação

Preferência inicial:

- partida completa;
- resolução nativa;
- sem crop;
- HUD visível;
- shop visível durante planning;
- scouting de alguns adversários;
- pelo menos uma tela de augment;
- sem compressão extrema.

O vídeo é usado apenas como fonte visual/replay.

## 2. Primeira amostra

Começar pequeno: **20–50 timestamps anotados**.

Distribuição sugerida:

- 8–12 planning/shop;
- 4–8 board/bench;
- 4–8 scouting/opponents;
- 3–6 augment;
- 3–6 momentos de transição de stage/level/HP/gold.

A meta da primeira rodada é descobrir falhas de percepção, não treinar policy.

## 3. Preparar frames

Exemplo por intervalo:

    python -m training.prepare_replay_annotations match.mp4 \
      --output-dir training/annotations/match-001 \
      --every-seconds 30 \
      --max-frames 40

Para momentos específicos:

    python -m training.prepare_replay_annotations match.mp4 \
      --output-dir training/annotations/match-001 \
      --timestamps-ms 95000,123000,181500

## 4. Anotar

Editar `training/annotations/match-001/annotations.json`.

Preencher apenas o que está visualmente confirmado:

- hp;
- gold;
- level;
- xp;
- stage;
- shop;
- board_unit_ids;
- lobby_player_ids.

Campos desconhecidos podem ser omitidos.

## 5. Rodar replay pipeline

O replay deve gerar telemetria JSONL contendo:

- StateSnapshot;
- GameEvent;
- OpportunityFactBuild;
- CompleteOpportunityCycle;
- EvaluatorFeedbackSnapshot;
- métricas de latência.

## 6. Relatório

    python -m training.replay_calibration \
      telemetry/data/match-001.jsonl \
      --annotations training/annotations/match-001/annotations.json \
      --annotation-tolerance-ms 250 \
      --output telemetry/data/match-001-calibration.json

## 7. Gates iniciais

Os números abaixo são gates de engenharia para investigação, não alegações de precisão já atingida.

### HUD

- HP exact accuracy >= 0.98
- Gold exact accuracy >= 0.98
- Level exact accuracy >= 0.99
- Stage exact accuracy >= 0.99

XP pode exigir gate separado conforme legibilidade/resolução.

### Shop

- shop slot accuracy >= 0.97
- unknown rate <= 0.02

### Board

- board recall >= 0.95
- board precision >= 0.95

Não promover decisões agressivas de item/pivot quando a confiança visual relevante estiver abaixo do gate configurado.

### Lobby/scouting

- lobby identity recall >= 0.98

Board adversário continua sujeito a consensus temporal e staleness.

## 8. Diagnóstico

Se um gate falhar, corrigir na ordem:

    ROI/calibration
    → preprocessing
    → detector/OCR
    → confidence calibration
    → consensus temporal
    → Opportunity evaluator

Não compensar percepção ruim alterando OpportunityWeights.

## 9. Depois do primeiro replay

    replay 1
    → replay 2/3
    → consolidar metrics
    → freeze baseline
    → Shadow/Swarm rewards
    → calibration report
    → candidate weights
    → weight-replay-diff
    → evaluation gate

## Regra principal

Nenhum peso, evaluator ou policy é promovido porque pareceu melhor em uma única partida.

Precisamos de:

- ground truth;
- amostra suficiente;
- baseline congelado;
- comparação reproduzível.
