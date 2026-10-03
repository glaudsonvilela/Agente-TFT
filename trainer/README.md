# Remote Trainer

O servidor BigBANANA funcionará como **Agente 2 / plano remoto de treinamento**.

O arquivo `compose.example.yml` define um contêiner próprio
`agente-tft-trainer` com dados em `./data`, limite de 1,5 CPU e 1 GiB.
A porta 8801 fica restrita ao loopback do servidor para acesso por túnel
autenticado. Defina `TRAINER_API_TOKEN` no `.env` do diretório do serviço.
`TRAINER_DB_PATH` ativa SQLite com WAL para sessões, pedidos e resultados.
O endpoint `/v1/training/health` informa `storage` e `simulator_ready`.
No estado atual, `simulator_ready=false`: o backend padrão preserva pedidos,
mas falha explicitamente com `simulator_not_configured` em vez de inventar
500 resultados. Consulte `docs/HM45_SIMULATION_STORAGE.md` para o caminho de
integração e os critérios das dicas.

## Endpoints planejados

```text
POST /v1/training/sessions
POST /v1/training/jobs
GET  /v1/training/jobs/{job_id}
POST /v1/training/jobs/{job_id}/cancel
GET  /v1/training/health
```

## Job

Entrada:

```text
GameState
DecisionPacket
mode
rollout_count
horizon_steps
opponent_pool
```

Saída:

```text
reward_mean
reward_stddev
placement_mean
top4_rate
first_rate
HP/gold after horizon
worker metrics
```

O servidor não recebe comandos de mouse/teclado e não controla o cliente TFT.


## Dois modos em paralelo

### 1. Realtime Shadow Player

Mantém uma linha contínua no simulador:

```text
real state rev 100
  ↓
shadow init
  ↓
aplica ação recomendada
  ↓
simula rev 101/102/...
  ↓
novo real state rev 101
  ↓
reconcile
  ↓
continua
```

Endpoints:

```text
POST /v1/shadow/sessions
GET  /v1/shadow/sessions/{shadow_id}
POST /v1/shadow/sessions/{shadow_id}/sync
POST /v1/shadow/sessions/{shadow_id}/step
POST /v1/shadow/sessions/{shadow_id}/end
```

### 2. Counterfactual Swarm

Abre muitos futuros independentes para a mesma decisão:

```text
GameState rev 100

ROLL 20G → N rollouts
LEVEL 8  → N rollouts
HOLD     → N rollouts
```

Usa:

```text
POST /v1/training/jobs
```

Os dois modos podem rodar ao mesmo tempo. O Shadow preserva sequência temporal; o Swarm mede alternativas.

## Pattern Engine

A experiência consolidada compara:

```text
ação recomendada
×
ação humana observada
×
ação Shadow
×
melhor branch contrafactual
×
outcome real
```

O objetivo é encontrar padrões repetidos em contexto, não transformar uma única simulação em regra.
