# calibration-inspect

CLI offline para transformar um snapshot serializado do
`EvaluatorFeedbackEngine` em um `CalibrationReport`.

Exemplo:

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-calibration-inspect -- \
  evaluator-feedback.json \
  --min-samples 50 \
  --min-abs-correlation 0.30
```

Saída:

```json
{
  "min_samples": 50,
  "min_abs_correlation": 0.3,
  "entries": [],
  "ready_for_weight_review": false
}
```

O relatório é somente para revisão/calibração offline.

Ele **não altera OpportunityWeights, confidence caps ou policy automaticamente**.
