# perception-core

Primitivas comuns para transformar leituras ruidosas de visão/OCR em observações estáveis.

## TemporalConsensus

Uma leitura só é promovida quando:

1. passa o threshold de confiança;
2. aparece de forma consistente pelo número configurado de confirmações;
3. as confirmações não estão separadas por um intervalo excessivo.

Exemplo:

```text
frame 101: gold=50 confidence=.93
frame 102: gold=43 confidence=.61  → ignorado
frame 103: gold=50 confidence=.95  → promovido
```

Isso evita contaminar o `GameState` com um erro visual isolado.
