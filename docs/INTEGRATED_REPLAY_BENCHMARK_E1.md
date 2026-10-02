# E1 — diagnóstico integrado: imagem até dica apresentada

## Pedido e estado

O usuário quer testar o projeto como uma experiência integrada, incluindo dicas,
demora e atraso percebido, para identificar gargalos antes de aperfeiçoar módulos
isolados. Apenas gravar e enriquecer um arquivo ao final não satisfaz esse teste.

Este documento complementa `WINDOWS_PASSIVE_RECORDER_C1_PROPOSAL.md`:
C1 coleta sessões; E1 exercita os componentes disponíveis em cadência real e
apresenta suas saídas num laboratório de replay. Não representa código executável,
compilação Windows, aprovação de um modelo ou conclusão da integração.

Base de código conferida: `cc80d6117385b5de42a592e9a1ab976499887e0d`.
Não alterar os PRs e pesos de U1/L1/L2/L3 para simular uma integração inexistente.

## Dois modos do protótipo proposto

- `record`: captura transparente e consentida de uma janela, armazenamento e
  métricas operacionais. Sem dicas estratégicas dinâmicas durante a partida.
- `replay-lab`: gravação já encerrada ou simulador local controlado. Imagens em
  ordem causal, captura/preparo, leitores, estado experimental, cálculo, texto e
  painel de dicas. O jogo não precisa estar em execução para esse ensaio.

A política oficial de TFT diferencia análise pós-partida de recomendações que
mudam em tempo real conforme o estado da partida. Fonte consultada:
https://developer.riotgames.com/docs/tft

Não chamar um cliente oficial, partida casual, partida contra bots, transmissão
ou vídeo poucos segundos atrasado de "laboratório offline" para contornar essa
separação. Não ocultar processos, fazer injeção/leitura de memória nem alterar
anticheat. Dicas em replay são testes sobre uma sessão passada, não aprovação
implícita de assistência ao vivo. O objetivo de desempenho permanece atendido por
reprodução causal em tempo real e ensaios explícitos de contenção.

## O que existe e precisa ser reutilizado

Inspeção do código, não prova de ligação ponta a ponta:

- `rust/crates/capture-core/src/lib.rs`: CaptureSource / FrameEnvelope, formato,
  stride, tamanho, fonte e frame. Há uma fronteira a reutilizar; o nome WindowsTft
  no enum não é uma implementação de captura Windows.
- `rust/crates/capture-replay/src/lib.rs`: lê vídeo por FFmpeg, reamostra fps e
  atribui tempo pelo índice/taxa alvo. Esse tempo não é timestamp nativo de captura.
- `rust/apps/opportunity-inspect/src/main.rs`: executa OpportunityEngine e a
  decisão local a partir de JSON com GameState e OpportunityFacts. Não obtém esses
  fatos diretamente da tela. Não apresentar facts de fixture como fatos percebidos.
- `rust/crates/opportunity-engine/src/lib.rs`: fatos especializados alimentam
  escores explícitos; por exemplo, ganho de força e probabilidade já chegam de
  outros componentes. Não confundir ranking heurístico com simulador completo.
- `rust/crates/decision-core/src/lib.rs`: escolhe candidatos e retorna Wait quando
  nenhum atinge confiança. Não inventar candidatos para uma dica parecer pronta.
- `agent/core/coach.py`: assemble_recommendation e fallback_explanation preservam
  ação/confiança do DecisionPacket. Existe texto determinístico reutilizável;
  deadline, cancelamento e apresentação assíncrona ainda precisam ser ligados.

## Caminho do ensaio

```
fonte com relógio independente do consumidor
  -> captura do player de teste OU injeção de frames [modos separados]
  -> frame compartilhado, identidade e transformação
  -> localizar regiões + OCR + sinais de banco/tabuleiro disponíveis
  -> observações com tempo, validade e origem
  -> estado experimental / fatos disponíveis
  -> motor de oportunidades e decisão real
  -> explicação determinística real
  -> entrega à UI e confirmação de apresentação
```

Chamadas remotas/LLM podem ser medidas como ramificação adicional identificada;
não bloquear a primeira saída na espera de uma explicação externa. Não simular
esse custo com uma frase fixa ou sleep e reportá-lo como inferência real. Texto
posterior nunca pode trocar ação/confiança nem pertencer a outra revisão de estado.

Usar o mesmo contrato e, onde possível, a mesma implementação de produtor de
frames, agendador, consumidores e UI pretendidos para o produto. Não criar uma
cadeia falsa rápida apenas para o benchmark.

## Informação incompleta não pode encurtar artificialmente o teste

Toda etapa declara `real`, `fixture_input`, `load_injection`, `not_connected`,
`not_applicable`, `blocked_missing_data` ou `failed`, sem converter ausência em 0ms.
O relatório inclui catálogo de capacidades executadas, versão/hash de cada módulo,
quantidade de oportunidades realmente avaliadas e tamanho do estado consumido.

Duas trilhas separadas:

1. Pixels de gravação -> percepção real -> estado parcial -> decisão permitida
   pelos dados -> UI. Se faltar identidade/tabuleiro, mostrar abstinência concreta,
   não preencher fatos para recomendar uma compra ou posição.
2. Estados controlados de laboratório -> avaliadores realmente implementados ->
   decisão/texto/UI. Exercita os estágios posteriores mesmo quando o leitor falha.
   Rotular a fronteira artificial e NÃO chamar isso de captura-ate-dica completa.

Vencer um teste de latência emitindo apenas Wait não demonstra prontidão. Separar
saídas acionáveis no replay, abstenções, respostas incompletas e respostas expiradas.
A carga de módulos futuros continua desconhecida. Um stress sintético não comprova
seu comportamento ou consumo real.

## Relógios, causalidade e apresentação

Cada trabalho transporta session_id, clock_domain, trace_id, frame_id,
source_timestamp, geometry_epoch, state_revision e origem dos campos requeridos.
Em processos Windows do mesmo host, usar QPC e frequência conhecida; não subtrair
performance.now de um processo de um timestamp de outro sem correspondência.
Fonte: https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps

Captura do player e entrada direta do arquivo são ensaios distintos:
- Direta: do instante em que o frame deveria ser liberado pela fonte até a UI.
- Captura: do timestamp da captura até a UI, mais atraso do player/da captura
  quando medido com uma janela-fixture cujo evento/numero de frame seja conhecido.
A segunda pode medir o backend Windows. A primeira não deve alegar fazê-lo.

Medir pelo menos:
- atraso da fonte: disponibilidade real menos liberação programada;
- espera na fila e processamento de cada estágio;
- captura/liberação -> decisão pronta;
- captura/liberação -> resposta aplicada/apresentada pela UI;
- idade do estado e do campo REQUERIDO mais antigo na dica;
- alteração visual conhecida -> primeiro resultado correspondente, quando houver
  marcador de evento confiável. Em vídeos não anotados, essa métrica pode faltar.

Registrar submit, UI receive, UI apply e, quando disponível, confirmação de
apresentação. Enfileirar um update, requestAnimationFrame ou retornar de uma API
não prova que os pixels apareceram no monitor. Sem confirmação apropriada, usar
rótulo ui_applied_estimate; latência física de exibição permanece não medida.
Relatar separadamente overhead da própria instrumentação.

Não somar medianas/p95/p99 de etapas para produzir percentis end-to-end. Calcular
por trace correlacionado. Para leitores paralelos, atribuir a espera à dependência
que bloqueou a decisão, não somar trabalho concorrente como caminho crítico.

## Replay em cadência real

O produtor usa relógio monotônico e PTS/tempo de origem. Em 1x, não espera OCR
terminar para liberar o próximo frame; do contrário, esconderia crescimento da fila.
Sem usar frames futuros, rótulos do teste, resultados finais ou GameState pronto
para completar uma observação atual. Pausa/seek abrem nova época e invalidam tarefas.

Tarefas têm limites e deadlines por classe. Retries e fallback aparecem como custo,
não somem das métricas. Um frame novo não precisa disparar todos os leitores; usar
mudança relevante + verificação periódica e validade por campo. Registrar eventos
perdidos, lacunas e atualizações tardias: coalescer frames pode perder transições.
Nunca reutilizar ouro/loja de uma época com tabuleiro de outra sem acusar incoerência.

## Filas e recursos

- Captura, persistência, percepção, cálculo, explicação e renderização não devem
  bloquear mutuamente por operações longas no callback de captura.
- Filas de capacidade limitada e reciclagem de buffers; latest-frame coalescing
  para tarefas visuais substituíveis, sem descartar silenciosamente eventos já
  estabelecidos. Captura para arquivo tem fila e contadores próprios.
- Modelo e executores residentes; startup/cold time separados de steady state.
  Reutilizar RGB e transformações compatíveis, com identidade e tempo de vida.
- Contar processos OCR, pixels copiados, conversões, chamadas remotas, tempo de
  codificação/hash/gravação, bytes por segundo, memória e utilização CPU/GPU.
- Se uma dica expirar, mostrar estado expirado ou não publicar; manter o evento
  bruto no log. Uma rede de 1ms sobre um frame antigo não é resposta de 1ms.
- Não carregar treinador durante a coleta/ensaio padrão. Tarefas de treinamento
  concorrentes só em ensaio explícito e com consumo reportado.

## Evidência existente: hipóteses prioritárias, não benchmark integrado

Resumos recebidos em execuções separadas, sem novos ensaios nesta publicação:

- L3 ONNX residente p50/p95: 1,460939 / 1,5685713 ms; preparo p50 22,1808755 ms;
  total por arquivo SEM refinamento p50/p95 24,5434895 / 31,5033667 ms.
- Shop S3 frame_ms p50/p95: 657,537976 / 695,806415 ms, total_ocr_process_calls 136
  no lote de 40 frames. Esse é o caminho completo do probe, NÃO tempo puro OCR.
- Shop S2 frame_ms p50/p95: 454,953635 / 497,156696 ms; caminho com menos controles.
- HP3 leitura de uma versão em várias janelas: medianas perto de 220..228 ms.

Prioridade: localizar custo dos probes/OCR e filas, preparação/cópia e consumidor
final. A rede pequena não parece dominar os custos de componente já reportados,
mas só a instrumentação integrada confirma o novo caminho. Não atribuir esses
números ao Windows, somá-los como latência final ou declarar Speedup controlado.
Há também gargalo funcional: os testes do mapa mantêm board_mapping_established
false e game_state_updated false. Isso pode deixar o motor ocioso e produzir uma
latência enganosa se forem contadas apenas as respostas sem dados.

## Matriz de ensaio e saída automática

Configuração congelada, pesos/fontes com hash e mesma gravação para pares:
A. Caminho real disponível com fonte 1x, persistência ligada e desligada.
B. Mesmo caminho com taxas de leitores controladas e carga de 30/60fps da fonte.
C. Estados-fixture no motor real, todos os tamanhos de candidatos suportados.
D. Contenção controlada CPU/GPU/disco em laboratório, sem jogo oficial conectado.
E. Coletor C1 junto de uma sessão própria somente após a revisão de compatibilidade:
   mede impacto de gravação no jogo, não faz dicas dinâmicas durante a partida.

Replay não reproduz perfeitamente a carga GPU de uma partida ativa. Reportar essa
limitação e distinguir contenção artificial do perfil do jogo. Nem A nem D substitui
medição real de impacto do coletor em E. Não contornar anticheat para coletar métricas.

Saídas propostas: trace.jsonl, frame-lifecycle.jsonl, capabilities.json,
recommendations.jsonl [somente replay], queue-metrics.json, summary.json e
comparison.txt. Reportar p50/p95/p99, distribuição/cauda, drops por motivo, timeout,
oldest-field-age, latência por resultado, overhead da medição e cobertura dos módulos.
Sem dados por trace não atribuir causalmente um pico à etapa de maior média.

## Ordem de implementação e critério de conclusão

Construir uma fatia vertical pequena, real e instrumentada, com painel de dicas de
laboratório, antes de exigir que toda percepção esteja perfeita. Ampliar a cobertura
nesse mesmo fluxo, sem recodificar um miniagente para cada teste. Não prometer o custo
do produto final com componentes que ainda não existem.

Primeiro marco verificável: entradas em tempo real de uma fonte de teste,
percepção/estado/fatos com procedência, motor real, explicação determinística e UI,
com traces correlacionados e indicação explícita de tudo que não foi conectado.
Depois: backend de captura Windows/empacotamento, recursos e calibração nativa.
A ordem da implementação pode combinar captura e UI, mas aprovação nunca depende
apenas de uma tela bonita exibindo mensagens predefinidas.

Publicação atual é especificação e inspeção de código. Nenhum executável, novo
benchmark, teste de aplicação, leitura ao vivo, dica em partida, promoção de perfil
ou atualização automática de pesos foi realizada. Os bloqueios e regressões
anteriores continuam abertos. GitHub recebe este documento no PR de C1; o estado
de merge é consultável separadamente.
