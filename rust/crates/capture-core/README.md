# capture-core

Abstração multiplataforma da entrada visual do Agente TFT.

O restante do sistema consome apenas `CaptureSource` e `FrameEnvelope`.

Backends planejados:

- `StaticFrameSource` — fixtures/golden tests;
- `ReplayVideoSource` — vídeos e replays no Ubuntu;
- `DesktopSource` — desenvolvimento/calibração;
- `WindowsTftSource` — captura live no Windows.

A lógica de percepção, estado e decisão não deve saber qual backend produziu o frame.
