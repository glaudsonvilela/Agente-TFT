# opportunity-runtime

Orquestrador do ciclo principal de decisão.

Entrada:

```text
GameState
OpportunityFacts
MetaSnapshot (optional)
timestamp
```

Saída atômica:

```text
OpportunityReport
OpportunityDelta
DecisionPacket
Remote OpportunitySummary[]
should_refresh_ui
should_remote_evaluate
```

Garantias:

- a decisão local vem do mesmo shortlist enviado ao servidor;
- rede nunca bloqueia a decisão;
- ciclos sem mudança material não disparam Swarm repetido;
- `reset()` reinicia tracking entre partidas;
- o UI pode atualizar apenas quando `OpportunityDelta` é material.

Esse crate é o ponto preferencial de integração do loop live/replay.
