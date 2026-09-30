# hud-runtime

Pipeline reutilizável para transformar frames em estado HUD estabilizado.

```text
FrameEnvelope
   ↓
HudLayout (ROIs normalizadas)
   ↓
preprocess variants
   ↓
HudOcrEngine
   ↓
domain validation
   ↓
ambiguity suppression
   ↓
TemporalConsensus
   ↓
StateFusion
   ↓
GameEventKind
```

O runtime não depende de Tesseract especificamente; qualquer backend que implemente `HudOcrEngine` pode ser usado.
