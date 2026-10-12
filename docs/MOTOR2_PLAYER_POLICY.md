# Política de jogador do Motor 2

Objetivo: aprender a escolher jogadas de TFT a partir dos dados estruturados
que o Motor 1 entrega e que o Motor 2 Rust integra e pontua. A política produz
uma **ação tipada** e uma justificativa apoiada nos fatos da decisão. Não recebe
uma pergunta livre nem decide por texto gerado.

## Fluxo implementado

1. O Motor 1 lê HUD, loja, tabuleiro, reserva, itens, sinergias, aumentos e
   adversários, preservando origem, idade e incerteza.
2. O Motor 2 recebe essa leitura, integra o estado da partida e devolve estado,
   histórico, alternativas e notas de utilidade. A resposta agora inclui cada
   alternativa avaliada e a observação atual, além da opção selecionada.
3. `hm.motor2_player_feed.make_frame` grava o estado causal, as alternativas e
   um vetor numérico com indicadores de valores ausentes. A preferência atual
   do Rust **não** é convertida em demonstração humana.
4. `training.export_motor2_player_sft` aceita somente uma jogada revisada e
   alinhada ao quadro exato, com lista explícita das alternativas legais.
5. `training.decision_lab` pode treinar uma pequena rede para pontuar essas
   alternativas por imitação supervisionada. Otimização por preferência só
   roda se houver pares revisados em treino e validação.
6. `training.build_player_episodes` agrupa as leituras em partidas completas,
   com início, fim e colocação revisados. Mantém cada instante e a memória
   causal na ordem, em vez de misturar quadros independentes.

Hoje o passo 5 é um caminho de treino, não uma política ativa. O replay continua
a usar a decisão do Motor 2 Rust. Nenhum modelo foi promovido.

## Dados e avaliação necessários

- Confirmar pelo conteúdo de cada partida o patch, o jogador, a integridade do
  vídeo e o resultado. Data de publicação isolada não confirma o patch.
- Anotar, em cada decisão, o estado **antes** da ação, a ação vista **depois**,
  o conjunto de alternativas legais, o resultado e as evidências que sustentam
  a anotação. Se a ação do jogador não estiver entre as alternativas do Rust,
  corrigir o gerador de alternativas antes de usar aquela cena para treino.
- Separar treino, validação e teste por partida inteira; reportar acerto da
  ação, ganho/regret em avaliação validada, desempenho por tipo de jogada,
  cobertura de estado e latência por decisão. Acerto em dados sintéticos mede
  imitação do professor sintético, não força no jogo real.
- Ramificações contrafactuais só podem ensinar preferências depois de validar
  o simulador e comparar alternativas com sementes pareadas. Desfecho de uma
  única partida não prova que outra ação seria melhor.
- Uma fala de jogador será condicionada à ação escolhida, fatos observados e
  objetivo de jogo (economia, tempo, sobrevivência, composição). Nunca deve
  afirmar como fato um campeão adversário, item ou probabilidade incerta.
  A fala é saída da decisão; não participa da legalidade da jogada.

O canal escolhido para revisão é TFT-HuanMie, registrado em
`configs/training/huanmie-source-candidates-20261011.json`. A Riot publicou o
18.4B em 7 de outubro; os vídeos candidatos foram publicados depois, mas o
patch das partidas ainda precisa de confirmação visual. O manifesto de regras
`configs/strategy/TFTSet18/18.4B/readiness.json` ainda marca os componentes
como não verificados. Por isso o treino competitivo e a promoção permanecem
bloqueados, mesmo com a ligação de dados pronta.

## Ramificações Dyna

O método pedido é aprendizado baseado em modelo, frequentemente chamado de
**Dyna**: em cada estado real da partida, testar alternativas em cópias do
simulador. A mesma semente de loja, combate e eventos deve ser aplicada a
todas as alternativas comparadas. Cada ramo produz uma distribuição de
colocações, não uma vitória garantida. Só as diferenças de resultado acima da
incerteza do simulador poderão virar preferência de treino.

O simulador do repositório hoje roda em laboratório sintético e bloqueia o
perfil do patch atual. Ele ainda não executa partidas completas do 18.4B nem
foi validado contra replays independentes. Portanto milhares de ramos podem
ser usados agora apenas para testar o método e medir custo, sem atualizar a
política competitiva. O próximo requisito é paridade do simulador com partidas
reais completas, incluindo economia, loja, aumentos, sinergias, itens,
combate e adversários.

## Conferência das regras do 18.4B

A referência oficial é a [nota da Riot para 18.4 e atualização B de 7 de
outubro](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/).
Ela traz **mudanças** de sistema, unidades, características, itens, wisps e
aprimoramentos, além de correções e desativações. É preciso aplicar os deltas
de 18.4 e depois os de 18.4B; a nota não é uma especificação completa de
todos os estados e efeitos do jogo.
Também é necessário conferir a [visão geral do
set](https://teamfighttactics.leagueoflegends.com/en-sg/news/game-updates/enchanted-wilds-overview/)
e as notas de [18.1](https://teamfighttactics.leagueoflegends.com/en-sg/news/game-updates/teamfight-tactics-patch-18-1/),
[18.2](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-2/)
e [18.3](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-3/),
pois regras anteriores continuam relevantes até serem alteradas. Ainda assim,
notas públicas podem omitir probabilidades, gatilhos e casos especiais.

`training.audit_full_simulator_18_4b` confere cada entrada conhecida do
catálogo, cada alteração oficial catalogada, os 13 componentes de prontidão,
integridade dos arquivos e a existência de um executor de partidas completas
para o patch. O relatório detalhado fica em
`experiments/dyna-synthetic-probe-20261011/full-simulator-18.4B-audit.json`.
Seu status atual é **blocked**: 91 campeões, 36 características e 1.444
efeitos constam no catálogo, mas seus efeitos ainda são só referências, não
regras executáveis validadas. Os 92 deltas base e 32 deltas B registrados
também não estão ligados a regras validadas. Há 76 descrições de habilidade
com marcadores não resolvidos; os parâmetros econômicos vieram de 18.3B e
precisam de conferência para 18.4B. Faltam o executor de partidas completas e
a validação dos 21 sistemas de partida discriminados no relatório, entre eles
ofertas elegíveis de wisps, compartilhamento da pool, economia, combate,
adversários e apuração da colocação.

O validador de exemplos de decisão agora rejeita preferências geradas por
ramificações simuladas de 18.4B enquanto essa auditoria estiver bloqueada.
Exemplos reais revisados continuam elegíveis para imitação supervisionada.
Um campo de prontidão marcado manualmente não substitui a comparação com
partidas reais independentes.
