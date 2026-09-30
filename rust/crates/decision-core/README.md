# decision-core

Seleciona uma ação canônica a partir de candidatos **já avaliados** por matemática/policy.

Este crate não define estratégia de TFT e não inventa pesos.

Entrada:

```text
CandidateDecision
├── action
├── utility       # maior = melhor, definido pelo produtor
├── confidence
└── evidence
```

Saída:

```text
DecisionPacket
├── action vencedora
├── confidence original do candidato
├── alternatives
└── evidence
```

Regras:

- candidatos abaixo da confiança mínima são descartados;
- utilidades não finitas são descartadas;
- empate é determinístico;
- se nenhum candidato for confiável → `WAIT`;
- margem pequena adiciona evidência de ambiguidade, sem adulterar a confiança.

O PydanticAI recebe apenas o `DecisionPacket` final e não pode trocar a ação.
