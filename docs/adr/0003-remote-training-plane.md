# ADR-0003 — Remote Training Plane no servidor BigBANANA

**Status:** Accepted  
**Date:** 2026-09-30

## Contexto

O Agente TFT local precisa aprender com muito mais episódios do que uma partida real permite produzir. O servidor do BigBANANA pode ser usado como plano remoto de treinamento para executar simulações, self-play e bot pools em paralelo.

Foi considerada a ideia de o servidor assumir controle remoto do cliente real. Essa topologia foi rejeitada para o projeto live. O treinamento remoto deve operar sobre **estado estruturado e simulador**, não sobre mouse/teclado do TFT.

## Decisão

Criar dois papéis independentes.

### Agente 1 — Local

Responsabilidades:

- percepção;
- GameState;
- TFT Math;
- scouting observado;
- DecisionPacket;
- recomendação ao usuário;
- recorder;
- envio opcional de jobs para treinamento remoto.

### Agente 2 — BigBANANA Server

Responsabilidades:

- receber `TrainingJobRequest`;
- validar protocolo e idempotência;
- executar rollouts em simulador;
- enfrentar scripted bots e policy snapshots;
- agregar reward/outcome;
- devolver `TrainingJobResult`;
- armazenar datasets e métricas de treinamento.

## Fluxo

```text
Agente 1 local
     │
     │ GameState + DecisionPacket
     ▼
Remote Training API
     │
     ▼
Agente 2 / Worker Pool
     │
     ├── simulator
     ├── scripted bots
     ├── historical policies
     └── self-play
     │
     ▼
TrainingJobResult
     │
     ▼
dataset / evaluation / policy training
```

## Regra de isolamento

O protocolo remoto não possui primitivas de:

- mouse;
- teclado;
- janela;
- processo;
- DLL;
- memória;
- driver;
- desktop remoto;
- execução de ação no cliente TFT.

Isso mantém o servidor como **plano de treinamento**, e não como executor live.

## Benefícios

- milhares de rollouts por decisão observada;
- comparação contrafactual: “e se tivesse rolado 20g?”;
- bot pool com estratégias variadas;
- avaliação contínua do policy model;
- treinamento sem bloquear o PC local;
- BigBANANA pode escalar workers independentemente do cliente.

## Segurança e autenticação

O transporte deverá usar:

- TLS;
- token de sessão curto;
- `session_id`;
- `job_id` idempotente;
- limites de rollout/horizonte;
- timeouts;
- rate limiting;
- nenhum segredo gravado na telemetria.

## Gatilho de sessão

No produto, o usuário poderá habilitar uma **sessão remota de treinamento**. Isso é um handshake lógico entre Agente 1 e Agente 2 — não acesso remoto ao sistema operacional.

## Consequência

O agente local continua funcionando mesmo sem o servidor. O Remote Training Plane é acelerador de aprendizagem, nunca dependência do caminho crítico da recomendação.
