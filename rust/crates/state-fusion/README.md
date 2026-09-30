# state-fusion

Mantém o `GameState` canônico e recebe observações já produzidas por percepção.

Fluxo:

```text
OCR / Vision candidate
       ↓
TemporalConsensus
       ↓
stable observation
       ↓
StateFusion
       ↓
GameState revision
       ↓
state-engine
       ↓
GameEventKind
```

Leituras de baixa confiança ou inconsistentes não alteram o estado.
