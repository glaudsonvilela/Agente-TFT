# A1.5 — coordenador de trabalho diagnóstico com histórico persistente

Base: A1.4, `e9c7a86612a593e60f5d6a1a2090fe4a0347c052`.

## Ponto de partida confirmado pelo usuário

A importação A14 no Ubuntu reportou revisão 1, `changed=true`, candidata
`quarantined`, referência de baseline preservada, `activation_allowed=false`
e `restart_read_verified=true`. Isso comprova a verificação reportada de uma nova
conexão, não reboot físico, treinamento ou precisão de HP. A referência do HP1
continua tendo falhas conhecidas: não é ground truth.

A1.5 passa a consultar esse registro antes de planejar trabalho. Não acrescenta
outra calibração do Match001 e não libera a candidata `hp_text_fit_v1`.

## Componentes implementados

- `training/perception_coordinator.py`: política de agendamento, sinal temporal
  e reserva idempotente de intenções de diagnóstico.
- `training/coordinate_hp5_perception.py`: adaptador de relatórios HP5 verificados,
  já importados no A14; reproduz registros, não imagens.
- `scripts/coordinate_match001_perception.sh`: comando de execução local.

A14 é consultado sem importar outra revisão ou migrar seu esquema. O diário
A1.5 usa OUTRO arquivo: `telemetry/data/perception-registry/coordinator.sqlite3`.
Não confundir esse diário com perfis ativos, pesos ou o GameState.

## Visibilidade e persistência do problema

O agendamento recebe somente timestamp, hash registrado da imagem, status do
leitor e unicidade do marcador. Não recebe HP esperado, texto reconhecido ou
valores numéricos para escolher uma decisão.

- Marcador não encontrado, ambíguo ou busca sem resultado válido:
  `visibility_unresolved`; não significa oclusão comprovada nem drift visual.
- Falha operacional: `operational_error`, separada de recalibração.
- Marcador único com falhas persistentes de leitura: candidato a `degraded`.
- Repetição do mesmo hash de imagem não avança contadores de deterioração.

Defaults de diagnóstico: blocos NÃO sobrepostos de 8 frames, intervalo de até
750 ms, pelo menos 1000 ms entre início/fim de cada bloco, três blocos ruins
consecutivos e dois bons para recuperação. Mais de 20% de ausência de leitura
no bloco caracteriza bloco ruim. O limiar é de AGENDAMENTO, não de confiança do
OCR. Nenhum limite de OCR foi alterado. Lacunas e perda de visibilidade quebram
o suporte temporal; um frame ruim não vira múltiplos votos de drift.

O resultado é um sinal do coordenador, não um snapshot nativo A1.1 fabricado.
Hashes diferentes da tela toda também não garantem pixels de HP independentes.
A causa de ausência do marcador continua desconhecida sem outros sensores.

## Histórico, duplicação e orçamento

O coordenador lê a referência do contexto e a identidade do candidato no A14.
Dados já registrados como avaliados por esse mesmo par/contexto recebem
`skip_already_evaluated`. Não são reenviados ao OCR porque o script foi reiniciado.
O adaptador HP5 verifica novamente o histórico com o importador A14 e exige o
MESMO evidence_id presente no registro; não confia no resumo colado no console.

Uma fonte nova, registrada por um adaptador confiável, só pode gerar uma intenção
shadow se houver deterioração persistente, candidato registrado sem bloqueios e
orçamento disponível. Candidata em quarentena continua podendo ser examinada
pelos probes explícitos existentes, mas NÃO recebe retry automático por este
coordenador. Renomear um arquivo não cria outra identidade do leitor.

A chave de pedido inclui contexto, par de leitores, tempos e hashes de frames;
não inclui nome do lote ou hora de execução. Status alterado para os mesmos
frames causa erro. Sobreposição com frames já reservados não cria outra tarefa.
Reservas sobrevivem à reabertura, inclusive as marcadas como falhas.

Defaults de orçamento: uma intenção pendente por contexto, até três intenções
ou 192 frames por hora, intervalo mínimo de 60 s para o mesmo par. O relógio de
agendamento é separado do PTS da gravação. Regressão do relógio falha fechada,
sem zerar custos. Limites e cooldown são decisões persistidas: rerodar a MESMA
entrada depois não contorna o limite. Fonte nova precisa trazer dados novos.

## Persistência e limites de execução

Decisão, reserva de custo e relógio são gravados na mesma transação SQLite
`BEGIN IMMEDIATE`, `synchronous=FULL`. Snapshot com checksum; esquema/política
incompatível ou corrupção interrompem sem reset. Até 2000 decisões e 8 MiB;
excesso falha explicitamente. Destino não pode substituir o registry A14.

Reservar NÃO executa uma tarefa. Não existe worker ou dispatcher nesta entrega.
`finish_intent` é confirmação interna de estado para o worker futuro; não é
prova de execução. Antes de executar qualquer reserva no futuro, o worker terá
de revalidar registro, fontes, escopo e orçamento. Nenhuma reserva concede
ativação. Um resultado antigo reutilizado traz também os bloqueios atuais.

Banco local de um usuário; não é autenticação, serviço multi-tenant nem garantia
contra reescrita maliciosa por quem controla os arquivos. Crash de processo
exercitado em testes não substitui validação de filesystem/power-cut físico.

## Executar no Ubuntu

```bash
cd "$HOME/Agente-TFT"
bash scripts/coordinate_match001_perception.sh \
  "telemetry/data/match-001-player-hp5.TP4E2p1M"
```

Não roda Cargo, Tesseract, FFmpeg ou treinamento. O executável/config são somente
rehashados pelo importador; imagem/vídeo não são abertos. Hashes de mídia continuam
referências históricas, não revalidação dos bytes das imagens neste passo.

Cria saída nova `telemetry/data/a15-coordinator.XXXXXXXX/report.json`. Imprime
`A15_SEQUENCE`, `A15_SUMMARY`, `A15_REPORT`. Para os três trechos HP5 já registrados,
a expectativa é zero novas intenções. Na primeira execução há três decisões
persistidas; na segunda, mesmas decisões sem aumentar a revisão do diário.
Os bloqueios do A14 permanecem e `runtime_connected=false` continua explícito.

## Validação e próximo bloco

Testes locais do núcleo: suporte temporal, oclusão não inferida, duplicatas,
quarentena, consulta atualizada do registry, retomada, falha após escrita antes
do commit, concorrência, cooldown, orçamento, relógio e corrupção. Integração
HP5/A14 testa a cadeia real de validadores sobre relatórios sintéticos e proíbe
subprocessos. O CI executa as duas suítes; resultados são registrados no PR.

A1.5 liga registry e planejamento diagnóstico, NÃO o loop de captura. A1.6 deve
ligar fontes de observação e um worker limitado a esse coordenador, sem promover
a candidata histórica. Detector visual de visibilidade, geração de candidatas,
avaliação semântica, ativação/reversão e treinamento são capacidades separadas
que ainda precisam de integração/implementação. Não anunciar autoaprendizado
completo ou correção da confusão 36/56 a partir deste módulo.
