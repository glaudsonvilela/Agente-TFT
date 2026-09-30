# agent/

Camada de orquestração baseada em **PydanticAI-slim**.

Responsabilidades:

- consultar GameState;
- chamar ferramentas determinísticas;
- consultar policy/knowledge quando necessário;
- resolver conflitos;
- produzir `Recommendation` estruturada;
- gerar explicação curta.

Não responsabilidades:

- captura de tela;
- loop de visão;
- cálculo de odds;
- inventar confiança;
- armazenar a verdade do estado.

Estrutura prevista:

```text
agent/
├── core/
├── tools/
├── schemas/
├── prompts/
└── tests/
```
