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
`127.0.0.1:8802`. A imagem e o configurador ficam no BigBANANA
em `~/agente-tft-voice/current`. Em 2026-10-04, a voz aprovada pelo operador
foi configurada e o contêiner independente foi ativado com reinício automático.
A chave e o Voice ID ficam somente no arquivo privado do servidor.

O teste real de sessão e `/v1/voice` entregou a frase de boas-vindas em
714,88 ms (3,669 s de áudio); a repetição devolveu o mesmo áudio em 6,89 ms.
São duas medições locais no servidor, sem comprovar latência ou reprodução
no Windows. Evidência: `docs/evidence/voice-api-20261004/approved-voice-activation.json`.
O endereço para clientes é `https://tft.bigbanana.io`, configurado em
`configs/services/voice.json`. A aplicação publicada no túnel Cloudflare
`bigBANANA` aponta para o gateway local `http://127.0.0.1:8803`.

No BigBANANA, o comando abaixo pede a chave sem eco, pede o Voice ID e sobe
somente o contêiner de voz já compilado:

```bash
~/.local/bin/tft-voz-configurar
```

A partir do Ubuntu conectado à mesma rede:

```bash
ssh -t glaudsonvilela@10.0.0.174 /home/glaudsonvilela/.local/bin/tft-voz-configurar
```

O comando verifica a inicialização local; autenticação na ElevenLabs e qualidade
de áudio exigem uma geração real posterior. Não imprimir o arquivo privado,
não enviar a chave pelo chat e não incluir esse arquivo na coleta de sessões.

Na raiz do repositório no servidor, a configuração interativa não mostra a chave:

```bash
PYTHONPATH=apps/hud_mapper:trainer python3 -m companion_service.configure
```

Ela salva `~/.config/agente-tft/voice.env` com permissão 0600. Ao reprovisionar,
use o Voice ID da voz aprovada; o nome de uma prévia não identifica o ID.

O operador configura `ELEVENLABS_API_KEY` e `ELEVENLABS_VOICE_ID` somente no
servidor (arquivo de ambiente privado, fora do Git) e executa, na pasta trainer:

```bash
docker compose --env-file /caminho/privado/voice.env -f compose.voice-service.yml up -d --build
```

O gateway Nginx do perfil Compose `public` limita o corpo HTTP a 4 KiB,
restringe os caminhos/métodos da API e aplica limite de solicitações. Ele usa
32 MiB / 0,25 CPU, escuta apenas em `127.0.0.1:8803` e roda sem privilégios.
O HTTPS público é terminado pela Cloudflare e segue pelo túnel criptografado;
o trecho HTTP entre cloudflared, gateway e aplicação permanece no servidor.

Para iniciar o gateway junto com o serviço:

```bash
docker compose --env-file /caminho/privado/voice.env -p agente-tft-voice -f compose.voice-service.yml --profile public up -d --no-build
```

Em `voice.env`, `TFT_VOICE_TRUSTED_PROXIES` deve conter `127.0.0.1` e o
gateway da rede Docker `agente-tft-voice_default` (no BigBANANA: `172.20.0.1`).
Confira o gateway ao recriar essa rede. Nginx aceita `CF-Connecting-IP` somente
do cloudflared em loopback e substitui `X-Forwarded-For`; Uvicorn só confia nos
endereços configurados. Isso preserva os limites por IP sem confiar em cabeçalhos
enviados diretamente por clientes externos. Outros sites/túneis não são alterados.

Novos builds Windows incorporam o endereço acima; instaladores anteriores
não recebem essa configuração automaticamente. O host do serviço pode
receber texto narrado e nick/região para consulta de histórico; não recebe
quadros da captura. Não há RSO nem chave Riot neste serviço.

Endpoints: `GET /health`, `POST /v1/session`, `POST /v1/voice` e
`POST /v1/player-summary`. Sessões anônimas duram 24 horas; tokens ficam em
memória no cliente e somente hashes no SQLite do servidor. O registro é
público por projeto: **não é uma licença ou prova de identidade**. Há limites
de criação de sessões, uma síntese por vez, 6 falas/minuto por instalação,
120/dia e reserva global de 20.000 caracteres por 24 horas. IDs de instalação
não são identidades fortes; o orçamento global limita consumo mesmo se forem
trocados. Falhas em tentativas de síntese também consomem a reserva;
orçamento não é estimativa de preço. Áudios encontrados no cache não reservam
caracteres, mas continuam exigindo sessão e respeitando os limites de requisições.

### Cache persistente de frases

O serviço guarda o PCM validado em `/data/voice-audio.sqlite3`, no volume Docker,
com até 512 entradas e 64 MiB de áudio (mais a estrutura do SQLite). Cada áudio
expira após 30 dias; o cache remove os menos usados recentemente quando atinge
o limite. Apenas o áudio solicitado é carregado em memória.

A chave do cache inclui o texto exato, voz, modelo, idioma, formato e revisão
dos parâmetros. Portanto, uma nova voz/modelo não reutiliza a gravação anterior.
Mudanças futuras de pronúncia/configuração devem atualizar `cache_identity()`.
Não são salvos texto legível nem credenciais nos metadados; o próprio áudio pode
conter informações narradas, por isso o volume deve permanecer privado.

Frases fixas, como boas-vindas e instruções recorrentes, são geradas uma vez
e reutilizadas entre sessões, instalações e reinicializações enquanto a entrada
permanecer válida. Não há geração antecipada paga de frases que talvez não sejam
usadas. Textos diferentes são sintetizados normalmente. A decisão de quando
falar permanece no cliente; um áudio em cache não torna uma dica aplicável.

`/health` informa `audio_cache.entries`, `audio_bytes`, `hits` e
`characters_reused`; o último conta caracteres que deixaram de ser enviados
novamente ao provedor, não créditos ou dinheiro. `/v1/voice` informa
`X-TFT-Voice-Cache: hit|miss`. Áudio corrompido ou expirado é descartado;
falha de leitura do armazenamento interrompe a solicitação para evitar novas
chamadas pagas em sequência.

O histórico exige um adaptador `fetch(nickname, region, patch, set_key, limit)`
que devolva identidade exata, fonte, data e partidas normalizadas. Sem adaptador,
a resposta é `external_history_unavailable`. O módulo `player_summary` calcula
somente ranked do set/patch de `TFT_ACTIVE_KNOWLEDGE` (arquivo do catálogo); o
cache inclui essas versões e invalida na atualização. Para trocar o patch,
atualize o arquivo e reinicie o serviço. Não há análise neural treinada aplicada
a esse resumo; não inferir erros de rolagem a partir de colocações finais.

Os testes automatizados do serviço usam transporte ElevenLabs simulado,
sem credenciais e sem chamadas pagas. A ativação descrita acima foi validada
separadamente com áudio real. O endpoint HTTPS está configurado; a reprodução
e a latência dentro do aplicativo instalado no Windows ainda exigem teste nesse
sistema. O resumo de partidas também depende de conectar uma fonte válida de histórico.
