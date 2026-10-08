# Comentário de combate e acompanhamento de adversários

## Sinais usados

* O comentário de derrota exige estágio legível, vida aceita pelo leitor e
  duas leituras estáveis do valor menor. A animação de dano não gera mensagens
  repetidas. Saltos de estágio e reinícios do vídeo reiniciam a observação. A
  derrota é uma inferência da queda de vida, ainda sem leitura independente da
  tela de resultado.
* O painel direito é lido pelo worker Rust a cada cinco segundos, em uma
  tarefa independente da leitura do tabuleiro. Nomes e valores de vida são
  candidatos de tela; o painel de dano é descartado. Um valor de vida só entra
  no histórico após duas leituras concordantes.
* O adversário atual só é associado quando o nome acima do tabuleiro concorda
  com um nome repetido no painel. O registro de derrota ligada a esse nome é
  candidato temporal, não uma identidade de conta ou rótulo de treino.

## Reprocessamento

* Na sessão `hm4-20261008-010358-980828`, a vida observada passou de 90
  para 88 e depois 86 no estágio 2-6. O detector emitiu um único evento aos
  52,4 segundos, depois de 86 aparecer em duas leituras. Outros dois registros
  com saltos de vídeo e leituras inconsistentes não geraram evento.
* Uma captura 1920×1080 da sessão `hm4-20261008-015458-469549` permitiu ler
  sete nomes e sete valores de vida no painel. Em outra fonte, a área direita
  mostrava “Damage Dealt”; o parser descartou essa tela em vez de criar
  jogadores falsos.
* A OCR do painel custou cerca de 1 a 1,5 segundo nas imagens avaliadas. Ela
  foi movida para uma tarefa assíncrona com intervalo de cinco segundos para
  não ficar no caminho da resposta do tabuleiro. A fluidez da prévia ainda
  precisa ser observada em uma sessão longa no Windows.
* No vídeo de seis horas escolhido pelo usuário, os quadros de 8:50 a 9:15
  mostraram os sete adversários e o confronto com Xbmots. O nome do próprio
  jogador foi lido separadamente. O quadro de 17:40 mostrou “Damage Dealt”:
  a lista anterior permaneceu como histórico e os valores de vida passaram
  a ser exibidos como sem leitura atual. Quando a lista voltou aos 21:05,
  as leituras de vida dos adversários voltaram a atualizar.
* Vinte e sete recortes do painel, nome de adversário e identificação do
  jogador foram guardados em
  `/mnt/sherlock-ssd/AgenteTFT/diagnostics/opponent-crops-20261008` com
  horário, região e hash. São observações sem rótulo. As futuras sessões também
  registram `opponent-crop-observations.jsonl` junto às capturas completas.

## Limite atual

Ainda não atribuímos a composição e os itens de um tabuleiro visitado ao
adversário correto. O painel mostra nomes, vida e confrontos observados;
ações de posicionamento contra um adversário específico dependem dessa
associação. A narração de vitória também exige uma evidência de resultado que
vá além da própria vida permanecer igual.
Os recortes alimentam a coleta para avaliação posterior, mas ainda não alteram
pesos da rede neural. Este vídeo é de outro conjunto do TFT; seus campeões e
itens não devem ser usados como rótulos do patch atual.
