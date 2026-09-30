# Documentação

## Leitura recomendada

1. [Escopo do produto](PROJECT_SCOPE.md)
2. [Arquitetura](ARCHITECTURE.md)
3. [Engenharia](ENGINEERING.md)
4. [Roadmap](ROADMAP.md)
5. [ADRs](adr/)

## Contratos principais

O projeto será guiado por três contratos versionados:

- `GameState` — o que o sistema acredita estar acontecendo;
- `GameEvent` — o que mudou;
- `Recommendation` — o que o coach manda fazer e com qual confiança.

Esses contratos devem permanecer independentes de UI, modelo e fonte de percepção.
