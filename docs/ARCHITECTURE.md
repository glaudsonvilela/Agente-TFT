# Arquitetura — Agente TFT

## Visão geral

```text
                         TFT
                          │
              ┌───────────┴───────────┐
              │                       │
       captura / visão           Riot / fontes
          Rust/ONNX              autorizadas
              │                       │
              └───────────┬───────────┘
                          ▼
                    STATE FUSION
                          │
                    EVENT ENGINE
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
      TFT MATH        POLICY MODEL     KNOWLEDGE
        Rust             ONNX          local/cache
          └───────────────┼───────────────┘
                          ▼
                   PydanticAI-slim
                          │
                          ▼
                  DECISION FUSION
                          │
                          ▼
                    Tauri/Svelte
```

## 1. Caminho crítico

O caminho crítico deve permanecer fora do LLM:

```text
frame → percepção → fusão de estado → evento → cálculo → candidatos
```

Responsabilidade principal: **Rust**.

Metas:

- baixa latência;
- memória estável;
- dados tipados;
- ausência de bloqueio causado por chamadas de modelo;
- funcionamento degradado mesmo sem LLM.

## 2. Perception Layer

Entradas possíveis:

- captura de regiões específicas da tela;
- OCR para gold, HP, nível, XP e estágio;
- detector/classificador para unidades, itens e augments;
- template matching para elementos estáveis;
- tracking temporal para reduzir reconhecimento redundante.

Saída:

```text
Observation<T> {
    value,
    confidence,
    source,
    observed_at,
    frame_id
}
```

Nenhum dado visual crítico deve entrar no GameState sem confiança.

## 3. Riot/Data Layer

Funções:

- identificar patch e versão;
- obter metadados oficiais disponíveis;
- histórico para avaliação;
- assets e dados estáticos;
- informações de sessão que APIs oficiais disponibilizem.

A API não deve ser assumida como substituta da visão. O sistema faz **fusão de fontes**.

## 4. State Fusion

O GameState é a verdade central.

Exemplo conceitual:

```text
GameState
├── match
├── player
│   ├── hp
│   ├── gold
│   ├── level
│   ├── xp
│   ├── board
│   ├── bench
│   ├── shop
│   ├── items
│   └── augments
├── lobby
│   └── opponents[]
├── history
└── confidence
```

Cada campo preserva origem, timestamp e confiança quando relevante.

## 5. Event Engine

Eventos importantes:

- MATCH_STARTED
- ROUND_CHANGED
- SHOP_CHANGED
- BOARD_CHANGED
- BENCH_CHANGED
- GOLD_CHANGED
- HP_CHANGED
- LEVEL_CHANGED
- ITEM_ADDED
- ITEM_EQUIPPED
- AUGMENT_SCREEN
- COMBAT_STARTED
- COMBAT_ENDED
- OPPONENT_OBSERVED
- CONTESTATION_CHANGED

Eventos determinam **qual módulo precisa recalcular**.

## 6. TFT Math

Código determinístico para:

- economia e breakpoints;
- odds de loja;
- custos de level;
- unidades observadas fora da pool;
- contestação;
- valor de upgrades;
- regras/traits;
- score de risco;
- candidatos de ação.

O LLM nunca é a fonte de verdade desses cálculos.

## 7. Policy Model

Modelo treinado para estimar valor de ações.

Entrada: representação estruturada do GameState.

Saída exemplo:

```json
{
  "hold": 0.08,
  "level": 0.11,
  "roll_10": 0.23,
  "roll_20": 0.49,
  "roll_until_upgrade": 0.09
}
```

Treino em Python/PyTorch; inferência em produção preferencialmente ONNX.

## 8. PydanticAI-slim

Papel: **orquestração e interpretação**, não loop de captura.

Ferramentas previstas:

- get_game_state
- get_economy_analysis
- get_board_analysis
- get_shop_analysis
- get_item_analysis
- get_upgrade_probabilities
- get_meta_context
- get_patch_rules
- evaluate_actions
- explain_decision

Saída obrigatoriamente validada por schema Pydantic.

## 9. Decision Fusion

Combina:

- policy;
- matemática determinística;
- confiança das observações;
- contexto de patch;
- restrições de produto;
- explicação curta.

Se a confiança do estado for baixa, a saída deve expressar incerteza ou solicitar nova observação, não fabricar precisão.

## 10. UI

A janela lateral precisa privilegiar velocidade de leitura:

```text
ROLL 18–22G

Player 2 está contestando X.
Pare quando X chegar a 2★.

Confiança 84%
```

Detalhes ficam sob demanda.

## 11. Perfis de execução

- **lab** — simulador, datasets e experimentos;
- **replay** — vídeo/VOD/replay;
- **live-approved** — somente funcionalidades revisadas contra políticas aplicáveis.

A arquitetura deve permitir habilitar/desabilitar capacidades por perfil sem forks de código.


## Opportunity Engine — núcleo obrigatório

Toda recomendação passa por este estágio antes de chegar ao `DecisionPacket`.

```text
GameState
   ↓
specialized facts
   ├── economy
   ├── shop/pool
   ├── board strength
   ├── items
   ├── positioning
   ├── scouting
   └── external meta prior
   ↓
Opportunity Engine (Rust)
   ↓
ALL opportunities
   ↓
local utility ranking
   ↓
shortlist
   ├── Decision Core → resposta local imediata
   ├── Shadow Player → linha contínua
   └── Counterfactual Swarm → branches profundos
```

### Regra

O motor mantém duas saídas:

- `all`: todas as oportunidades válidas avaliadas;
- `shortlist`: pequeno subconjunto para avaliação profunda.

Nenhum candidato é omitido apenas por ter score baixo; ele continua disponível em `all` para auditoria e replay.

### Utility

A utility local combina, de forma explícita e versionada:

```text
immediate_board_gain
upgrade_value
hp_preservation
economy_value
contest_urgency
flexibility
information_value
external_meta_prior
uncertainty_penalty
```

Utility é score de ranking, não probabilidade.

Os pesos iniciais são baseline heurístico e deverão posteriormente ser calibrados/substituídos por policy/modelos avaliados.

## External Meta Context

Fontes estatísticas externas são tratadas como **priors limitados**.

Exemplo de fonte: MetaTFT.

```text
MetaTFT/public snapshot
       ↓
normalize + provenance
       ↓
local MetaSnapshot
       ↓
patch/set/freshness gate
       ↓
bounded prior
       ↓
Opportunity Engine
```

O contexto externo pode conter:

- comps;
- units;
- items/builds;
- traits;
- augments;
- ranking/player style.

### Regras

- nunca consultar site externo no hot path;
- provenance obrigatório;
- patch/set mismatch invalida o snapshot por padrão;
- snapshot stale é ignorado;
- influência externa é limitada;
- GameState e matemática local têm prioridade;
- não usar endpoints privados/undocumented como dependência do projeto.

Exemplo:

```text
META:
comp X historicamente forte → +0.06

LOBBY:
6 cópias da carry observadas fora → -0.42

RESULTADO:
Opportunity Engine pode rejeitar o pivot.
```

## Realtime Remote Evaluation

Depois do shortlist:

```text
top opportunities
   ├── Shadow Player
   │     mantém uma linha sequencial
   │     + reconcile contra o estado real
   │
   └── Counterfactual Swarm
         executa múltiplos rollouts
         das melhores alternativas
```

O Pattern Engine agrega:

```text
recomendação
× ação humana observada
× Shadow
× melhor branch
× outcome
```

O BigBANANA é acelerador de avaliação/training; falha de rede não bloqueia a decisão local.
