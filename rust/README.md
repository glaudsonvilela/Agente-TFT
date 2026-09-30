# rust/

Caminho crítico de baixa latência.

Crates previstos:

```text
rust/
├── capture/
├── vision/
├── state/
├── events/
├── tft-math/
├── riot-api/
├── inference/
└── telemetry/
```

Princípios:

- nenhuma chamada LLM no hot path;
- filas limitadas;
- timestamps monotônicos;
- schemas serializáveis;
- métricas por etapa;
- fallbacks explícitos.
