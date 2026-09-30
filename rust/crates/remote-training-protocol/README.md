# remote-training-protocol

Contrato entre o Agente 1 local e o Agente 2 remoto no servidor.

O protocolo foi desenhado para **treinamento/simulação**, não para controlar o cliente TFT ao vivo.

Fluxo:

```text
Agente 1
  ↓
GameState + DecisionPacket
  ↓
TrainingJobRequest
  ↓
Servidor BigBANANA / Agente 2
  ↓
simulator / bot pool / self-play
  ↓
TrainingJobResult
  ↓
dataset / evaluation / policy training
```

Propriedades:

- versionado;
- idempotente por `job_id`;
- estado e decisão devem ter a mesma `revision`;
- rollout e horizonte limitados;
- heartbeat separado;
- nenhum campo de mouse/teclado/controle remoto;
- resultado contém reward e métricas agregadas, não "cliques".
