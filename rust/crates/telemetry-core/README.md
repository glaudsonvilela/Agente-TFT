# telemetry-core

Recorder auditável em JSON Lines.

Cada sessão cria um arquivo:

```text
telemetry/data/<session_id>.jsonl
```

Tipos de registro:

- session_started;
- state_snapshot;
- game_event;
- analysis;
- decision;
- recommendation;
- player_action;
- outcome;
- metric;
- session_ended.

## Objetivo

Permitir reconstruir:

```text
GameState
  ↓
eventos
  ↓
análises
  ↓
DecisionPacket
  ↓
Recommendation
  ↓
ação do jogador
  ↓
resultado
```

Frames/vídeos não são duplicados no JSONL. Dados volumosos devem ficar fora do recorder e ser referenciados por metadados/hashes quando necessário.

Secrets, API keys e tokens nunca devem ser enviados à telemetria.
