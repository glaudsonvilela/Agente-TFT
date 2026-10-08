# Recuperação das dicas ao vivo — 7 de outubro de 2026

## Evidência da sessão que não deu dicas

A sessão `hm4-20261004-190825-730054` no SSD contém 78 leituras do leitor e
76 mensagens, todas sem ação. As imagens mostram área de trabalho, fila e
carregamento durante a maior parte dos 392 segundos; o tabuleiro aparece no
final. No leitor daquela instalação, o estágio era `unknown` mesmo quando
ouro, nível, XP e nomes da loja já estavam legíveis. Reexecutar o leitor Rust
atual nos quadros preservados `000009857.png`, `000010682.png` e
`000011360.png` recuperou, respectivamente, `1-3`, `1-3` e `1-4` com consenso
de duas escalas. Esse resultado prova a correção **nesses três quadros**, sem
medir precisão geral.
Com o OCR residente ativo neste Ubuntu, os quadros `000010682.png` e
`000011360.png` levaram 79,1 ms e 109,7 ms na chamada do leitor nativo.
É um ensaio local de dois quadros, não uma medição de latência no Windows.

Ainda havia uma dependência indevida no coach: exigia estágio e nível para
qualquer dica provisória. No registro do quadro 10996, a loja continha duas
cópias legíveis de Rakan e havia 4 de ouro; o preço catalogado das duas era
2 de ouro. Antes da correção, o replay dos 78 registros produzia zero ações.
Com a compra de par independente do estágio e nível, o mesmo replay produz
uma ação. A dica é hipótese baseada na loja e no ouro, sem alegar que conhece
o tabuleiro ou que a compra garante vitória. A regra de juros agora usa estágio
e ouro sem exigir nível; rolagem e XP conservam as informações necessárias.

## Reconhecimento visual entre quadros

O HUB preserva o melhor candidato de cada espaço do tabuleiro, inventário e
item equipado por até três leituras recentes. Dois quadros concordantes tornam
o nome um `persistent_candidate` **apenas se o quadro atual concordar**. Troca
de posição, salto de replay, lacuna de mais de 5 segundos e desaparecimento
da região descartam o histórico. Essa contagem não é probabilidade calibrada,
rótulo de treino ou identidade verificada. O painel Tabuleiro mostra possíveis
nomes e mantém essa distinção explícita.

A ideia de associar observações fracas a uma trajetória é compatível com o
artigo original [ByteTrack](https://arxiv.org/abs/2110.06864). Nossa
implementação é uma memória curta de posições fixas do TFT, sem Kalman,
reidentificação ou as métricas de acurácia daquele trabalho.

## Caminho da prévia e das dicas

Nos registros de telemetria da mesma sessão, a prévia teve aproximadamente
30 FPS durante boa parte da captura e 23,6 FPS no último relatório. O p95 de
renderização local do último relatório foi cerca de 5 ms; isso não prova um
gargalo de desenho. Em alguns intervalos, a idade antes do envio por IPC
ultrapassou 1 segundo. O aplicativo agora drena até quatro quadros antigos da
fila WGC antes de processar o mais recente e registra quantos descartou. Isso
segue a possibilidade documentada de consumir os quadros pendentes pelo
[Windows.Graphics.Capture](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture).

No estúdio com a nova interface, a codificação JPEG da prévia passa a ter uma
thread dedicada. O ciclo que publica dicas e aciona a voz não espera a
codificação. A fila da prévia continua com um único quadro substituível. O
teste automatizado suspende a codificação e confirma que uma dica ainda é
entregue. A melhoria de FPS/latência na máquina Windows ainda precisa ser
medida após a compilação; não há número de ganho observado no Windows.

O estado da interface distingue HUD de partida legível, estágio sem leitura de
economia e fonte sem HUD de partida. Diagnósticos como “não há regra para este
estágio” continuam nos registros técnicos, mas deixam de ocupar o cartão de
dicas como se fossem orientação ao jogador.

## Incremento de coaching parcial

Um nome da loja ligado de forma única ao catálogo pode agora gerar uma compra
de sinergia se duas unidades **distintas** forem candidatas persistentes em
casas do tabuleiro, compartilharem uma característica com a oferta e o ouro
observado cobrir o preço. O quadro do HUB deve ter no máximo 3,5 segundos e a
loja deve estar atual. A ação diz que é provisória; não supõe estrela,
ocupação confirmada, patamar ativado ou sucesso da compra. Se os candidatos
sumirem, envelhecerem ou estiverem no banco, essa dica não é emitida.

A interface mantém uma ação visível por até cinco segundos mesmo que a leitura
seguinte produza só diagnóstico. Os botões “Sim” e “Não” permitem avaliar a
dica atual. O feedback muda apenas a ordem de prioridade das famílias de
conselhos; não vira rótulo visual ou peso neural sem revisão.

## Próxima evidência necessária

As [notas oficiais 18.4](https://teamfighttactics.leagueoflegends.com/en-gb/news/game-updates/teamfight-tactics-patch-18-4/)
foram publicadas em 6/10/2026. O pacote de conhecimento instalado neste
checkout ainda declara 18.3; cálculos de força, características e itens que
mudaram não devem ser descritos como validados em 18.4. O
[Data Dragon de TFT](https://developer.riotgames.com/docs/tft) separa os
ativos por versão, mas a própria Riot informa que pode demorar a publicar a
atualização. A rota rápida é atualizar o pacote sazonal e validar deltas do
patch, mantendo captura, geometria e leitor de texto independentes dele.

Medir numa partida/replay mais longo, com quadros de planejamento dos estágios
2 a 5: cobertura de OCR de estágio/ouro/loja, frequência das famílias de dicas,
latência captura→dica→voz, nomes de unidades/itens por fonte independente e
taxa de associação item→portador. As dicas de composição, posicionamento e
equipamento precisam de estado suficientemente confiável; a persistência de
candidatos acima não o cria por si só. O pacote Windows ainda precisa ser
compilado e exercitado na máquina de destino.
