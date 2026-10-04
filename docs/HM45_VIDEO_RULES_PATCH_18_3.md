# Guia enviado × patch TFT 18.3

Vídeo local: `videoplayback.mp4`, 20m57s, SHA-256
`fa867f9689a25504387e40020f3531870a42f3c0ab582720f7476977d592f905`.
Áudio em português e quadros foram revisados como material de referência,
não como especificação executável. A transcrição automática contém erros.
Fonte do patch: [notas oficiais 18.3](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-3/),
incluindo 18.3 B (24/09) e atualização intermediária (28/09/2026).

| Trecho | Conceito do vídeo | Cruzamento com 18.3 | Destino |
|---|---|---|---|
| 00:15–03:30 | Tabuleiro, PvE/PvP, vida perdida por estágio e sobreviventes | As notas 18.3 não anunciam mudança na estrutura básica; corrigem um erro que podia omitir monstros PvE. A tabela exata de dano do vídeo não foi validada para 18.3. | Estrutura para o simulador; números de dano pendentes. |
| 03:30–07:40 | AD, AP, velocidade de ataque, crítico, armadura, resistência, vida, mana; componentes e alcance | O patch altera campeões, itens e emblemas. O catálogo versionado cobre os atributos base de 74/74 campeões, mas só 2/74 habilidades têm variáveis numéricas disponíveis na fonte; todas as descrições têm marcadores sem resolver. | Usar atributos conhecidos para perfil/posição; combate calculado fica bloqueado até completar valores e fórmulas. |
| 06:30–07:45 | Sinergias ativadas pelo número de unidades | O patch 18.3 muda valores de Defensor, Caçador, Inferno, Invocador e outras sinergias. | Quebras e efeitos são dados por patch; nunca embutir no layout do tabuleiro. |
| 08:00–11:25 | Ouro, juros até 50, XP, loja e conjunto compartilhado de cópias | A nota 18.3 não altera expressamente a regra geral de juros/XP do vídeo, mas encantos, aumentos e recompensas especiais alteram a economia. Também corrige contagem temporária de cópias em Pandora's Bench. As probabilidades e tamanhos exatos do conjunto precisam de fonte e teste próprios. | Motor econômico básico com exceções explícitas; distribuição de loja pendente. |
| 11:25–14:15 | Slow roll e fast 8 | São estratégias condicionais, não regras do jogo. Dependem de vida, ouro, nível, unidades disputadas, itens e patch. | Ações candidatas do MCTS, nunca dica fixa. |
| 14:15–16:00 | Espátula, frigideira, removedor, reforjador | As mecânicas gerais continuam úteis, mas 18.3 altera valores de emblemas e corrige itens reforjáveis. | Catálogo de item e transformação por patch; não recomendar equipamento só porque há item no inventário. |
| 16:00–17:45 | Fogos-fátuos/Wisps no espaço direito da loja | 18.3 ajusta custos, bônus e frequência de vários Wisps; **Major Polymorph foi desabilitado em 28/09**. | Ações e disponibilidade por data/patch; vídeo não serve como tabela atual de valores. |
| 18:00–20:55 | Exemplos de composições, carregador provisório e itens | Exemplos de estratégia do autor. 18.3 e 18.3 B alteram poder de campeões como Veigar, Kha'Zix, Camille e Teemo. | Casos de estudo para comparação com partidas observadas; não são rótulos de “melhor jogada”. |

## Como os dados entram no laboratório

1. A geometria 4×7 e as regiões de HP/ouro continuam em `configs/ui`.
2. Campeões, atributos, traços, itens e disponibilidade ficam em releases por
   set/patch, com hash e origem. O release 18.3 foi salvo em `knowledge/releases`.
3. Partidas de jogadores Desafiante podem fornecer **composições finais
   observadas** e resultados. O importador `ingestion/challenger_patterns.py`
   exige coorte e versão do cliente explícitas. O histórico público da Riot
   não fornece cada compra, rolagem e posição de cada rodada; o vídeo de uma
   partida ou telemetria autorizada são necessários para esses estados.
4. O agregador JIT calcula estatísticas de trajetórias dadas. O motor que gera
   transições legais, combate, loja e resultados ainda precisa ser validado
   antes de produzir simulações TFT ou treinar uma política a partir delas.

MetaTFT pode indicar jogadores e tendências publicadas, mas o importador usa
respostas identificáveis da API oficial da Riot como fonte de resultados. Não
há coleta automática nem reprodução de dados privados do MetaTFT neste pacote.
