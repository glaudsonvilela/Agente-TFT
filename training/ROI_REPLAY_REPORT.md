# ROI replay report

Resume o JSONL gerado por `agente-tft-roi-replay-inspect`.

## Uso

```bash
python3 -m training.roi_replay_report \
  telemetry/data/match-001-roi-events.jsonl \
  --output telemetry/data/match-001-roi-report.json
```

O relatório mostra por ROI:

- quantidade de mudanças;
- mudanças por minuto;
- score p50/p95/máximo;
- gap temporal p50/p95;
- primeiro/último evento;
- combinações de ROIs que mudam no mesmo frame.

## Interpretação

Esse relatório mede comportamento do **change detector**, não accuracy.

Exemplos:

- `shop` quase nunca muda apesar de várias lojas no replay → ROI/threshold possivelmente errado;
- `board` dispara dezenas de vezes por segundo → threshold possivelmente sensível demais;
- `player_list` muda durante scouting/combate → esperado, mas precisa ser comparado ao vídeo;
- `gold` muda nos momentos de buy/roll/level → bom indício de ROI correta.

Thresholds só devem ser ajustados depois de comparar os eventos com cenas reais do replay.
