# ROI replay report

Resume o JSONL gerado por `agente-tft-roi-replay-inspect`.

## Uso

```bash
python3 -m training.roi_replay_report \
  telemetry/data/match-001-roi-events.jsonl \
  --output telemetry/data/match-001-roi-report.json
```

Parâmetros opcionais:

```text
--global-cut-min-rois 6
--episode-gap-ms 1500
```

## Schema v2

O relatório separa duas visões:

### `raw`

Tudo que o change detector emitiu.

Útil para depurar sensibilidade pura, mas inclui:

- fade/transição de tela;
- animações;
- primeiro frame de baseline;
- rajadas de vários frames para uma única mudança real.

### `semantic`

Exclui frames em que pelo menos `global_cut_min_rois` mudaram juntos.

Isso trata como provável **global cut / scene transition** eventos como:

```text
bench + board + gold + items + level_xp + player_list + shop + stage
```

O relatório também agrupa mudanças repetidas da mesma ROI separadas por até
`episode_gap_ms` em um único **episode**.

Por ROI são mostrados:

- raw changes;
- semantic changes;
- changes/minute;
- episodes;
- episodes/minute;
- mudanças brutas por episódio;
- duração mediana do episódio;
- score p50/p95/máximo;
- gap temporal p50/p95.

## Por que isso importa

Em TFT, uma mudança real pode gerar vários frames consecutivos de alteração por causa de:

- animação da shop;
- partículas do board;
- transições de combate;
- HUD piscando/atualizando;
- fade entre tabuleiros durante scouting.

Contar cada frame como um evento estratégico superestima brutalmente a atividade.

Exemplo:

```text
gold raw changes: 536
gold semantic episodes: 70
```

A primeira métrica diz "pixels mudaram".
A segunda se aproxima mais de "houve um episódio visual distinto".

## Regra

Esse relatório ainda mede comportamento do **change detector**, não accuracy.

Thresholds e coordenadas só devem ser alterados depois de:

1. remover global cuts;
2. agrupar episódios;
3. comparar episódios com frames/replay reais;
4. confrontar com ground truth.

Não ajustar OpportunityWeights para compensar ruído visual.
