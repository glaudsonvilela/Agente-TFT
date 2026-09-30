# weight-replay-diff

Compara um conjunto candidato de `OpportunityWeights` contra as decisões já
gravadas em telemetria.

Entrada:

1. JSONL contendo `complete_opportunity_cycle`;
2. JSON com pesos candidatos.

Exemplo:

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-weight-replay-diff -- \
  telemetry/data/match.jsonl \
  candidate-weights.json
```

Exemplo de config:

```json
{
  "weights": {
    "immediate_board_gain": 1.2,
    "upgrade_value": 1.0,
    "hp_preservation": 0.9,
    "economy_value": 0.8,
    "contest_urgency": 0.7,
    "flexibility": 0.5,
    "information_value": 0.4,
    "external_meta_prior": 1.0,
    "uncertainty_penalty": 0.8
  },
  "min_confidence": 0.6
}
```

Saída inclui:

- ciclos vistos;
- decisões alteradas;
- agreement rate;
- transições por classe de ação;
- baseline/candidate WAIT counts.

**Não mede qualidade.** Um peso que muda mais decisões não é melhor. Promoção
depende de reward/ground truth contra baseline congelado.
