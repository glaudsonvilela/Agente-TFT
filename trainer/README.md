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

## Painel e comando no BigBANANA

O quarto contêiner serve um painel leve em /dashboard. Ele mostra arquivos
guardados, sessões, caminhos solicitados e realmente concluídos, uma tabela
de até 12 execuções recentes, CPU e RAM do contêiner TFT e do servidor,
tempo por lote e versões de simulador/política. CPU é medida pela diferença
entre duas atualizações; a primeira leitura aparece como "medindo". Valores
indisponíveis são exibidos como tal, sem presumir zero. O estado da rede neural permanece
"treinamento não iniciado" até existir um processo real de aprendizagem.
O painel atualiza a cada cinco segundos, sem bibliotecas externas.

No servidor, o comando tft mostra um resumo; tft painel (ou tft acompanhar)
atualiza o próprio terminal a cada cinco segundos, incluindo CPU, RAM e a
tabela das execuções recentes. tft web mostra o endereço
da página caso o servidor tenha navegador.
O executável está em trainer/scripts/tft e pode ser ligado a
~/.local/bin/tft. O nome visual "!TFT" pode ser usado na interface, mas
no Bash o ponto de exclamação aciona a expansão do histórico; o comando
digitável é tft.

Como a porta só escuta no próprio servidor, abra um túnel SSH no computador
de onde verá o painel e depois visite http://localhost:8801/dashboard.
A autenticação é a do SSH; a API que recebe sessões e jobs continua
exigindo o token privado.
No Ubuntu de teste, trainer/scripts/tft-painel-ubuntu abre o túnel e a
página em um só comando; quando ligado a ~/.local/bin/tft-painel, basta
digitar tft-painel.

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


## Serviço independente de voz e resumo de jogador (0.6.2)

`companion_service` é separado do treinador e não acessa os outros contêineres.
`compose.voice-service.yml` reserva 0,5 CPU / 192 MiB e publica somente
`127.0.0.1:8802`. Ainda não foi implantado no BigBANANA.

Na raiz do repositório no servidor, a configuração interativa não mostra a chave:

```bash
PYTHONPATH=apps/hud_mapper:trainer python3 -m companion_service.configure
```

Ela salva `~/.config/agente-tft/voice.env` com permissão 0600. O Voice ID é
informado pelo operador; a prévia por nome não identifica um ID confirmado.

O operador configura `ELEVENLABS_API_KEY` e `ELEVENLABS_VOICE_ID` somente no
servidor (arquivo de ambiente privado, fora do Git) e executa, na pasta trainer:

```bash
docker compose --env-file /caminho/privado/voice.env -f compose.voice-service.yml up -d --build
```

Para outros PCs, configure um proxy HTTPS para essa porta, com limite de corpo
HTTP de 4 KiB e limitação de solicitações. Preencha `service_url` em
`configs/services/voice.json` antes do build Windows. O host do serviço pode
receber texto narrado e nick/região para consulta de histórico; não recebe
quadros da captura. Não há RSO nem chave Riot neste serviço.

Endpoints: `GET /health`, `POST /v1/session`, `POST /v1/voice` e
`POST /v1/player-summary`. Sessões anônimas duram 24 horas; tokens ficam em
memória no cliente e somente hashes no SQLite do servidor. O registro é
público por projeto: **não é uma licença ou prova de identidade**. Há limites
de criação de sessões, uma síntese por vez, 6 falas/minuto por instalação,
120/dia e reserva global de 20.000 caracteres por 24 horas. IDs de instalação
não são identidades fortes; o orçamento global limita consumo mesmo se forem
trocados. Erros também consomem a reserva; orçamento não é estimativa de preço.

O histórico exige um adaptador `fetch(nickname, region, patch, set_key, limit)`
que devolva identidade exata, fonte, data e partidas normalizadas. Sem adaptador,
a resposta é `external_history_unavailable`. O módulo `player_summary` calcula
somente ranked do set/patch de `TFT_ACTIVE_KNOWLEDGE` (arquivo do catálogo); o
cache inclui essas versões e invalida na atualização. Para trocar o patch,
atualize o arquivo e reinicie o serviço. Não há análise neural treinada aplicada
a esse resumo; não inferir erros de rolagem a partir de colocações finais.

Os testes do serviço usam transporte ElevenLabs simulado, sem credenciais,
sem chamada paga e sem comprovar voz real. A distribuição para usuários ainda
depende de provisionar HTTPS/ElevenLabs e conectar uma fonte válida de histórico.
