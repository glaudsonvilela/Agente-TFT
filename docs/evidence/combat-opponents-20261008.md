# Comentário de combate e acompanhamento de adversários

## Sinais usados

* O comentário de derrota exige estágio legível, vida aceita pelo leitor e
  duas leituras estáveis do valor menor. A animação de dano não gera mensagens
  repetidas. Saltos de estágio e reinícios do vídeo reiniciam a observação.
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

## Limite atual

Ainda não atribuímos a composição e os itens de um tabuleiro visitado ao
adversário correto. O painel mostra nomes, vida e confrontos observados;
ações de posicionamento contra um adversário específico dependem dessa
associação. A narração de vitória também exige uma evidência de resultado que
vá além da própria vida permanecer igual.
