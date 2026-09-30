# PydanticAI-slim coach

A camada do agente **não decide a jogada**.

O fluxo é:

```text
GameState
  ↓
TFT Math + Policy
  ↓
DecisionPacket
  ├─ action
  ├─ confidence
  ├─ alternatives
  └─ evidence
  ↓
PydanticAI-slim
  ↓
CoachExplanation
  ├─ reason_short
  └─ next_step
  ↓
assemble_recommendation()
  ↓
Recommendation final
```

Isso impede o LLM de alterar:

- ação;
- confiança;
- alternativas;
- evidências.

Ele só transforma a decisão já calculada em linguagem curta e útil durante a partida.

## Ferramentas atuais

- `get_game_state`
- `get_decision_packet`
- `get_economy_analysis`
- `get_board_analysis`
- `get_knowledge_context`

O modelo/provedor é fornecido em runtime. O core do agente não fica acoplado a OpenAI, Gemini, Anthropic ou modelo local.
