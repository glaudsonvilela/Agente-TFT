# Coach por atributos — experimento sem habilidades

Esta etapa atende à decisão de prosseguir sem habilidades e de tratar depois
a identidade visual dos campeões. Não certifica um coach completo de TFT.

## O que o código executa

O motor `hm.strategic_coach` recebe um estado completo, confirmado, da perspectiva
do jogador e em planejamento. Examina alternativas antes de gerar texto:

| Família | Alternativas e restrições |
| --- | --- |
| Rolagem | Alvos a uma cópia de melhorar, presentes no tabuleiro; probabilidade da categoria no nível; orçamento limitado a cinco atualizações; reserva separada para a compra; limite de ouro e condição de parada. |
| Composição | Preencher uma vaga com uma peça do banco ou comparar todas as trocas individuais entre banco e tabuleiro. A peça substituída permanece no banco. |
| Posicionamento | Todos os movimentos e trocas nas 28 casas; alcance, contribuição de ataques básicos e cobertura do carregador por unidades próximas da frente. |
| Equipamentos | Item completo do inventário ou receita de dois componentes distintos; espaços disponíveis, unicidade e alternativa de conservar o item. Não equipa apenas por existir um componente. |

Uma recomendação prioritária segue para o caminho existente de voz. O histórico
mostra as quatro categorias disponíveis. São **alternativas**, reavaliadas após
cada ação, e não uma sequência para executar inteira sem nova leitura.

O catálogo sazonal fica em `configs/coaching/TFTSet18/18.3B-20260928`;
`active.json` fixa seus hashes. Geometria e lógica permanecem fora dos números
do patch. O compilador `training.build_coaching_catalog` reconstrói o catálogo
a partir do conteúdo de simulação, release selado e perfil de estrelas.

## Rede e significado do treinamento

`training.strategy_ranker_lab` gera estados sintéticos e treina uma MLP de
15 entradas, 32 unidades ocultas e uma saída: **545 parâmetros**. Há atualização
real dos pesos por gradiente. A rede aproxima um objetivo explícito de atributos,
formação, afinidade entre características e recursos.

Isso é **destilação de um avaliador projetado**, não aprendizado por vitórias,
imitação validada de desafiantes ou execução do algoritmo AlphaStar. Não usa os
10 mil testes anteriores de recursos como rótulos de estratégia. Vídeos ajudam
a formular hipóteses; narração isolada não é um estado/ação rotulado.

O split por semente é feito antes das alternativas: 80% treino, 10% validação,
10% teste. O checkpoint é escolhido somente pela validação. O teste compara
regret no objetivo, manter o estado e escolha aleatória, inclusive por família.
Concordância com o avaliador **não é taxa de acerto no TFT real**.

Os pesos exportados são JSON numérico, sem pickle. A inferência no aplicativo
usa somente a biblioteca padrão de Python. Torch permanece no treinamento.
O carregamento confere catálogo, esquema, objetivo, versão, tamanho e valores.

## Limites que continuam explícitos

- 73 entradas de campeões têm atributos utilizáveis. Kayle é rejeitada por
  ausência de AD no catálogo; nenhum número foi inventado.
- Há 27 itens vinculados e 18 receitas. Efeitos dinâmicos dos itens não entram
  neste objetivo; item desconhecido impede uma avaliação completa do estado.
- AP/mana sem execução de habilidades não mede o valor real de um carregador AP.
  O cálculo atual usa ataques básicos, resistência e HP. Isso pode alterar a
  preferência de composição/equipamento em relação ao jogo real.
- Afinidade de características não significa ativação ou simulação de todos
  os seus efeitos. Não há avaliação de aprimoramentos ou recompensas sazonais.
- A composição avaliada é uma mudança local das peças possuídas, não uma busca
  completa até a composição final. Posicionamento não prevê habilidades inimigas.
- A chance de rolagem usa aproximação de casas independentes e conjunto completo
  menos cópias próprias; não é uma chance exata com adversários desconhecidos.
  Formas de Lux compartilham a identidade do conjunto. O painel não apresenta
  essa estimativa como probabilidade observada.
- Nenhuma melhora de colocação em partidas reais está demonstrada.

## Ligação com a leitura da tela

`ReplayDecisionEngine.evaluate(..., strategy_state=...)` conecta o motor ao
formatador e à fila existente da ElevenLabs. O runtime aceita apenas o contrato
`snapshot.verified_state`, verifica época da captura e idade de até dois segundos
e rejeita incompatibilidade com uma leitura nova de ouro.

O observador B4 atual **não produz esse contrato**. Continua proibido converter
seus candidatos em identidades confirmadas. Portanto, as recomendações são
testáveis com estados conhecidos, mas estas mudanças sozinhas não liberam as
quatro dicas automaticamente sobre os pixels do Windows. Essa integração visual
foi explicitamente adiada pelo usuário nesta etapa.

Próxima etapa visual: rotular recortes reais por campeão, estrela, posição e
itens; separar treino/teste por partida; distinguir tabuleiro próprio/adversário;
calibrar rejeição de desconhecidos e rastrear mudanças temporalmente. Artes da
loja podem servir de catálogo, mas não substituem imagens dos modelos 3D. Primeiro
medir falsos reconhecimentos em sessões reservadas; depois habilitar o contrato.

## Fontes consultadas nesta etapa

- [dpei: posicionamento](https://www.youtube.com/watch?v=TXhQgEB6NS4): transcrição
  automática integral lida, 0:00–9:41; vídeo de 9:43. Critérios aproveitados como
  hipóteses: proteger o carregador, usar a frente para absorver dano e considerar
  cobertura lateral. Exemplos de sets antigos não foram tratados como atributos
  do patch atual. Nenhuma partida foi rotulada a partir desta transcrição.
- [Fundamentos do próprio criador](https://www.tftgameplan.com/fundamentals) e
  [partidas comentadas](https://www.tftgameplan.com/gameplay): índice consultado.
  Outros vídeos tentados não forneceram transcrição; não contam como revisados.
- [VODs de dpeitft](https://www.twitch.tv/dpeitft/videos): canal confirmado pelo
  link na descrição do YouTube. A gravação `2885789930` exige assinatura; somente
  os metadados foram consultados, sem contornar o bloqueio.
- [Relato original do AlphaStar](https://deepmind.google/blog/alphastar-mastering-the-real-time-strategy-game-starcraft-ii/):
  referência metodológica consultada; este experimento não reproduz sua escala,
  ambiente, treinamento com demonstrações ou liga de autojogo.

Relatórios numéricos e identidade dos pesos ficam em
`docs/evidence/strategy-coach-20261004`. Dataset integral e fontes ficam no SSD e
no diretório isolado do experimento no BigBANANA, fora do instalador.

## Resultado da execução de 04/10/2026

- BigBANANA: 10.000 estados, 202.765 alternativas de treino, 40 épocas,
  15.880 passos e quatro tensores alterados; 455,56 segundos, pico de 640,42 MiB.
- Pesos portáveis: 11.628 bytes; diferença máxima contra a inferência do treino
  de 3,89e-7. Arquivo incluído na configuração do pacote.
- O split inicial tem interação entre paridade das sementes e criação de pares:
  apenas 41 estados de teste tinham alternativas de rolagem. Por isso, uma
  auditoria adicional usou 500 sementes disjuntas, ambas as paridades e todas as
  81.757 alternativas. Incluiu 115 casos de rolagem e passou o limite declarado
  de regret médio abaixo de 0,025 em cada família, sem ajustar os pesos.
- Contrato de integração: 100 estados de teste produziram dicas e conteúdo para
  voz; p50 30,1 ms, p95 72,9 ms no computador de desenvolvimento. Não inclui
  leitura de pixels, conexão à API, reprodução de áudio ou execução no Windows.
- 36 testes de integração/regras passaram; um teste de áudio físico permaneceu
  ignorado, além de nove subtestes de rejeição de estado.

Não foi gerado um instalador novo. A configuração disponibiliza o ranker para
estados estruturados confirmados; o caminho visual continua sem identidade
confirmada e não foi promovido por estes resultados.
