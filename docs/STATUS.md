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
- CLI `calibration-inspect` para exportar relatório JSON;
- EvaluatorFeedbackSnapshot persistível na telemetria;
- `calibration-inspect` lê JSON puro ou último snapshot de um JSONL;
- Replay Calibration para coverage/latência/NO_CONFIDENT_CANDIDATE;
- primeiro replay real `TFT_MATCH_001.mp4` validado em 1920x1080/60 FPS (~32m39s);
- 40 frames estratégicos extraídos e pipeline de pré-anotação assistida por IA + revisão humana;
- baseline de layout `tft-1920x1080-match001-v1` para ROI detector e HUD OCR;
- HP removido do HUD estático: a linha local muda de posição na `player_list` e requer leitura dinâmica;
- relatório compacto de comportamento do ROI change detector.
- ground-truth replay accuracy para HUD/shop/board/lobby;
- ferramenta FFmpeg para extrair frames e criar template de anotações;
- Replay Intake Gate para validar vídeo + ground truth antes da calibração;
- validação de source_video, timestamps, duração, imagens, shop, HUD, board e lobby;
- labels opcionais de cena para auditar cobertura estratégica da primeira amostra;
- testes unitários do Replay Intake Gate integrados à suíte de training utilities.

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

Checkpoint funcional atual:

- GitHub Actions PR CI run: **#448**
- resultado: **SUCCESS**
- merge no main: `a7f03484e79b8c45c7dceee13de2c306316acbf3`
- branch congelada: `checkpoint/replay-intake-green-2026-09-30`
- checkpoint anterior preservado: `checkpoint/pre-real-replay-2026-09-30`

No mesmo run passaram:

- Rust workspace;
- Python agent/contracts;
- ingestion;
- training utilities;
- remote trainer.

Este é o ponto seguro de retorno com o intake do primeiro replay real já protegido por gate estrutural.

Regra: novas mudanças não invalidam este checkpoint; a branch acima permanece presa ao merge cuja árvore foi validada integralmente na CI #448.

## Próximos passos — ordem

1. **Validar baseline 1920x1080 no replay inteiro**
   - executar `roi-replay-inspect` com `configs/roi/tft-1920x1080-match001-v1.json`;
   - resumir eventos com `training.roi_replay_report`;
   - ajustar thresholds/ROIs somente contra evidência do replay real;
   - validar `stage/gold/level/xp` com HUD OCR.

2. **Replay accuracy / perception calibration**
   - medir HUD/shop/board/lobby;
   - corrigir ROI, preprocessing, OCR/detector e consensus;
   - revisar confidence caps.

3. **Weight calibration offline**
   - comparar baseline × candidate weights sobre ciclos gravados;
   - nunca promover pesos apenas por correlação;
   - exigir evaluation gate/replay antes de promoção.

4. **Weight promotion gate**
   - aprender/ajustar pesos candidatos fora da partida;
   - comparar contra baseline congelado;
   - promover somente depois de evaluation gate;
   - nunca alterar policy/pesos silenciosamente no meio de um match.

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
