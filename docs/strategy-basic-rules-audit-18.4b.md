# Auditoria das regras básicas e das ramificações — Set 18, 18.4B

Escopo: TFT padrão de oito jogadores. Os coeficientes abaixo são **candidatos**
da base local 18.3B; não foram promovidos a constantes 18.4B. As [notas
oficiais 18.4/18.4B](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/)
descrevem mudanças de unidades, características, itens, aprimoramentos e
Fogos-Fátuos, mas não publicam uma tabela completa de economia, chances de
loja e tamanho da pool. Ausência de alteração nas notas não é medição do jogo.

| Regra | Já representada no projeto | Situação para 18.4B |
| --- | --- | --- |
| Juros | `floor(ouro/10)`, até 5; Rust `tft-math` e projeção de rodada | Valor candidato; conferir em replay/cliente, inclusive a ordem em relação ao ouro da vitória. Aprimoramentos podem alterar o teto. |
| Ouro base e vitória | +5 por rodada PvP comum, +1 pela vitória na projeção | Candidato; etapas iniciais, PvE e efeitos especiais ficam fora. |
| Sequência de vitórias/derrotas | Após 2/5/6 resultados: +1/+2/+3 de sequência; reinício ao trocar o resultado | Candidato herdado de regras anteriores; conferir pagamentos e calendário do 18.4B. As [notas 14.8](https://teamfighttactics.leagueoflegends.com/en-sg/news/game-updates/teamfight-tactics-patch-14-8-notes/) documentam o bônus após dois resultados. |
| Dano ao jogador | Dano base por estágio + um por sobrevivente inimigo | Tabela local candidata; campeão, estágio e sobreviventes precisam ser observados. A mesma [nota 14.8](https://teamfighttactics.leagueoflegends.com/en-sg/news/game-updates/teamfight-tactics-patch-14-8-notes/) documenta a regra por sobrevivente naquela época. |
| Atualizar loja e comprar XP | 2 de ouro por atualização, 4 por 4 XP na tabela local | Candidato; o custo real precisa ser lido no HUD e modificado por efeitos da partida. |
| Chance por custo e nível | Tabela local completa de níveis 1–10; Rust rejeita linha que não soma 100% | **Não validada para 18.4B.** As [notas 16.1](https://teamfighttactics.leagueoflegends.com/en-gb/news/game-updates/teamfight-tactics-patch-16-1/) alteraram as chances dos níveis 8 e 9; copiar uma linha antiga sem revisão é incorreto. |
| Cópias por campeão na pool | 30/25/18/10/9 por custo na tabela local; Rust contabiliza cópias próprias e observadas nos rivais | Candidato; cópias ocultas e reservas de lojas adversárias continuam desconhecidas. Nunca subtrair uma peça inferida por palpite como se fosse observada. |
| Ofertas especiais, Fogos-Fátuos, aprimoramentos e passivas econômicas | Catálogo de referência e simulador experimental parcial | Não há cálculo geral validado para 18.4B; bloquear a ramificação correspondente até haver regra e estado observáveis. |

## Pool observada e sinergias do adversário

O caminho principal do Rust ainda subtrai apenas cópias vistas no tabuleiro
rival. Para preservar o rastreador existente, o módulo estratégico isolado
`strategy-analysis/opponent_belief.rs` recebe, à parte, leituras confirmadas
da reserva e das sinergias. Seu adaptador soma estrelas do tabuleiro e da
reserva (1/3/9 cópias), descartando leitura antiga, identidade não verificada
e duplicatas da mesma casa. **Essa contagem ampliada ainda não alimenta o
`opportunity-fact-builder` ao vivo.** Uma sinergia lida não subtrai cópias: pode restringir
a identidade de uma peça ainda sem nome, mas também pode resultar de emblemas,
efeitos especiais ou leitura incompleta.

Para o caso limitado de **uma** casa adversária sem identidade, o módulo
`strategy-analysis/opponent_belief.rs` calcula uma distribuição condicional. Para
cada candidato `u`, compara a contagem de sinergias prevista para
`tabuleiro_confirmado + u` com a leitura observada `t`:

`peso(u) = prior(u) × exp(-Σ_t confiança(t) × |contagem_observada(t) - contagem_prevista(t,u)| / escala_erro)`;

`posterior(u) = peso(u) / Σ_v peso(v)`.

Esse posterior só é permitido com exatamente uma peça não identificada,
painel completo verificado, modificadores de sinergia contabilizados e escala
de erro calibrada externamente. Ele não conta o candidato como peça confirmada. O OCR
ao vivo existente ainda marca `complete_panel_verified = False` e
`identity_verified = False`; portanto **essa inferência não está habilitada no
replay ao vivo**. Também falta um adaptador validado entre a observação visual
e a entrada isolada do motor estratégico. Os testes novos cobrem a matemática
e a separação, não substituem essa validação de ponta a ponta.

O “restante da pool” calculado a partir de cópias visíveis é um cenário
condicional, não o saldo exato: compras não vistas e lojas alheias continuam
ocultas. Até calibrar um modelo desse estado oculto, não devemos usar uma
chance pontual de rolagem como rótulo verdadeiro de treino.

## O que a ramificação nova calcula

`rust/crates/strategy-analysis/src/economy_branches.rs` recebe um estado
observado (ouro, HP e sequência), regras fornecidas e ações alternativas:
guardar, atualizar loja, comprar XP ou vender unidades com receita conhecida.
Para **cada** ação, devolve dois resultados condicionais para a próxima rodada
PvP comum: vitória e derrota. A decomposição mostra gasto, juros, prêmio de
sequência, renda, HP e eliminação. Uma derrota deliberada pode preservar ouro e
sequência, mas também pode eliminar o jogador; esse risco fica visível.

Exemplo matemático de teste, **não** previsão do 18.4B: com 50 de ouro, 20 HP,
quatro derrotas seguidas e dano de derrota igual a 9, guardar e perder deixa
62 de ouro, 11 HP e cinco derrotas. Gastar 2 em uma atualização e perder deixa
59 de ouro e 11 HP. A diferença vem dos 2 gastos e de 1 de juros. Vender
unidades por 3 de ouro dá 65 no mesmo ramo condicionado, mas altera o tabuleiro;
a probabilidade real de vitória e o número de inimigos sobreviventes mudariam.

Esse módulo **não** declara qual ação é melhor. Para ordenar caminhos até a
colocação final, ainda precisamos de: probabilidades calibradas de vitória por
tabuleiro e adversário, efeitos especiais, distribuição da pool oculta,
calendário e um simulador de partidas validado contra resultados reais. O
laboratório de partidas completas existente usa regras sintéticas; sua
colocação serve para testar a mecânica de busca, não como rótulo verdadeiro de
TFT. Nos vídeos, apenas a ação realmente tomada e seu resultado são observados.
Os outros ramos são contrafactuais estimados, sempre identificados como tal.

## Antes de treinar no Akash

1. Confirmar ou corrigir as tabelas candidatas no patch 18.4B por fonte atual
   ou por observações reproduzíveis do cliente; registrar hashes e origem.
2. Selecionar partidas completas de Desafiante e revisar estados, ações e
   resultados. Separar partidas inteiras entre treino, validação e teste.
3. Calibrar a previsão de vitória e medir erro das ramificações em partidas
   separadas. Recompensar colocação final e sobrevivência, além de ouro e
   força do tabuleiro; a estratégia de perder por economia só vale quando o
   risco compensar.
4. Só então gerar exemplos comparativos para a policy. Dados do simulador
   sintético ficam separados dos dados observados e não promovem pesos.

O gate executável em `training/prepare_challenger_strategy.py` agora separa
`data_split_ready` de `rule_coverage_ready`. O arquivo
`configs/strategy/TFTSet18/18.4B/readiness.json` mantém economia, loja, pool,
combate, habilidades, sinergias, itens, aprimoramentos, Fogos-Fátuos,
observação dos rivais e validação de replay como não verificados. Também exige
validar a policy que mantém plano entre rodadas e a fala ancorada em decisões,
sem comentários repetidos. O gate exige ainda
zero descrições de habilidade sem resolução. Portanto `training_ready` segue
falso mesmo que três vídeos revisados sejam selecionados; isso evita chamar
um catálogo incompleto de motor completo.
