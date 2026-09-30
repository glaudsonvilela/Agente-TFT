# STATUS — Agente TFT

Atualizado: 2026-09-30

Este arquivo é o checkpoint operacional curto do projeto. Ele complementa o ROADMAP e deve ser atualizado sempre que um bloco relevante muda de estado.

## Onde estamos

### Núcleo de decisão

Implementado:

- GameState / GameEvent / DecisionPacket versionados;
- Opportunity Engine em Rust como caminho obrigatório de decisão;
- Opportunity Tracker para mudanças materiais;
- Automatic / Complete Opportunity Runtime;
- todas as classes de ação centrais representadas:
  - BUY
  - SELL
  - ROLL
  - LEVEL
  - HOLD
  - EQUIP ITEM
  - POSITION
  - PIVOT
  - SCOUT
  - CHOOSE AUGMENT
  - WAIT;
- Fact Builder automático para buy/roll/level/scout/augment offers;
- Board Strength estrutural;
- item-strength estrutural;
- positioning-core;
- matchup-positioning contra adversário explicitamente observado;
- pivot-core estrutural;
- sell-core conservador;
- MetaTFT como prior externo limitado;
- CommunityDragon/Knowledge Pack local;
- telemetria tipada de OpportunityFactBuild e OpportunityCycle.

### Percepção / estado

Implementado ou estruturado:

- replay/capture pipeline;
- HUD consensus;
- shop consensus;
- opponent consensus;
- augment-options consensus;
- Board/bench geometry;
- confidence/source por observação.

Ainda precisa de calibração com imagens/replays reais do TFT.

### Treinamento remoto

Implementado:

- Agente 1 local ↔ BigBANANA Remote Trainer;
- Shadow Player contínuo;
- reconciliation contra GameState real;
- Counterfactual Swarm protocol;
- Pattern Engine;
- rewards do Shadow e do Swarm alimentando evaluator feedback;
- correlações OpportunitySignal × reward por ActionClass;
- correlações evaluator diagnostic × reward para item/pivot/position/sell;
- CompleteOpportunityCycle preservando diagnósticos especializados;
- CalibrationReport offline com min_samples/min_abs_correlation;
- CLI `calibration-inspect` para exportar relatório JSON.

O simulador pesado / bot pool definitivo ainda precisa ser ligado ao backend remoto.

### Meta externo

Implementado:

- MetaTFT browser collector público;
- normalização conservadora;
- comps/units/items/traits/augments/leaderboard;
- crosswalk para IDs canônicos;
- snapshot local, patch-aware e stale-aware;
- hot reload seguro;
- snapshots fora do Git.

## Estado da CI

HEAD no momento desta atualização:

`6b1aee32602253f219b79c0a455b53f43f2c791f`

CI em validação após correção da dependência runtime de `OpportunityFactBuild` em `telemetry-core`.

Regra: não considerar o checkpoint fechado até Rust + Python estarem verdes no mesmo HEAD ou sucessor direto.

## Próximos passos — ordem

1. **CI verde**
   - validar o checkpoint atual completo;
   - corrigir qualquer regressão;
   - congelar checkpoint.

2. **Feedback snapshot/export**
   - persistir snapshots do EvaluatorFeedbackEngine;
   - reproduzir CalibrationReport a partir de dados salvos;
   - manter dados de treino separados de secrets.

3. **Weight calibration offline**
   - aprender/ajustar pesos candidatos fora da partida;
   - comparar contra baseline congelado;
   - promover somente depois de evaluation gate;
   - nunca alterar policy/pesos silenciosamente no meio de um match.

4. **Real replay calibration**
   - usar gravações/screenshots reais;
   - medir HUD accuracy;
   - shop top-1 / unknown rate;
   - board recall;
   - opponent/scouting confidence;
   - Opportunity latency.

5. **BigBANANA simulator workers**
   - ligar simulador real ao ShadowBackend;
   - bot pool;
   - self-play;
   - historical-policy pool;
   - rollout parallelism.

6. **Policy training**
   - imitation/bootstrap;
   - PPO/self-play;
   - evaluation;
   - export ONNX;
   - inference Rust.

7. **UI**
   - AÇÃO;
   - motivo em uma frase;
   - próximo passo/stop condition;
   - confidence;
   - detalhes expandidos;
   - updates apenas em OpportunityDelta material.

## Regra arquitetural principal

```text
GameState
  ↓
automatic facts + specialized evaluators
  ↓
Opportunity Engine — ALL opportunities
  ↓
shortlist
  ├── local DecisionPacket
  ├── Shadow Player
  └── Counterfactual Swarm
  ↓
Pattern / evaluator feedback
  ↓
offline calibration / policy training
```

O LLM/PydanticAI explica a decisão; não fabrica probabilidades nem substitui os cálculos do Rust.
