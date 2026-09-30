# perception-board

Geometria e contratos para board/bench/scouting.

O crate **não implementa um detector de campeão**. Ele recebe detecções produzidas por um backend futuro (ONNX, modelo de visão etc.) e as associa a células calibradas.

```text
detector
  ↓
unit_id + bbox + confidence
  ↓
BoardGeometry
  ↓
nearest cell + distance gate
  ↓
conflict resolution
  ↓
AssignedUnit
```

A geometria é carregada de configuração; nenhuma coordenada real do TFT é hardcoded.

O mesmo mecanismo pode ser usado para:

- tabuleiro do jogador;
- bench, usando uma geometria de slots;
- scouting de adversários;
- replays de validação.
