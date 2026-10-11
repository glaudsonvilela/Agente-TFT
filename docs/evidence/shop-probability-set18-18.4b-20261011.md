# Probabilidade de encontrar uma unidade — TFT Set 18, patch 18.4B

Data da pesquisa: 2026-10-11. Escopo: loja normal da partida padrão e efeitos do Set 18 que mudam as ofertas ou a quantidade de oportunidades. Uma unidade obtida diretamente por efeito, carrossel ou duplicador usa outro mecanismo; não recebe a probabilidade da loja normal.

## Fontes e estado de verificação

- [Riot, notas do patch 18.4 e 18.4B](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/): regras e alterações recentes; 18.4B de 7 de outubro.
- [Riot, visão geral de Enchanted Wilds](https://teamfighttactics.leagueoflegends.com/en-sg/news/game-updates/enchanted-wilds-overview/): Fogos-Fátuos, Florescer, Fera do Rift, Teemo e LeBlanc.
- [Riot, patch 18.1](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-1/): Reserva de Pandora usa disponibilidade na pool; regras de alguns Aprimoramentos.
- [Riot, patch 18.3](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-3/): correção da Reserva de Pandora e suspensão temporária da Polimorfia Maior no 18.3, revista no 18.4.
- [Riot, patch 14.15](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-14-15-notes/): publicação da capacidade base 30/25/18/10/9. É uma fonte histórica, não confirmação independente para 18.4B.
- Catálogo local de 65 unidades: `champion-reset-20261009/experiments/combined-dino-corpus-20261011/source/roster/all-65.json`, reconciliado com Riot Data Dragon 16.20.1, 10 de outubro.
- Regras de economia **ainda fixadas em 18.3B**: `configs/coaching/TFTSet18/18.3B-20260928/catalog.json`. Elas são o ponto de partida abaixo. As notas do 18.4 não anunciam mudança nas chances de nível ou tamanhos de pool, mas não publicam uma tabela completa; portanto, tratar esses números como **parâmetros de trabalho a validar**, nunca como leitura direta do servidor 18.4B.
- Dados de habilidades, características, Fogos-Fátuos e Aprimoramentos 16.20: `diagnostics/patch-18.4-20261007/pt_br-16.20.json`. O [auditoria da fonte](../recognizer-training-20261005/patch-18.4-source-audit-20261007.md) registra discrepâncias entre dados estruturados e notas da Riot; texto de efeito não prova que um efeito está habilitado em toda partida.

## Tabela de trabalho para loja normal

As colunas são custos 1/2/3/4/5. Uma loja normal oferece cinco espaços; atualizar custa 2 de ouro, salvo efeito ativo. O número de campeões distintos por custo no Set 18 é 14/13/14/14/10.

| Nível | 1 | 2 | 3 | 4 | 5 |
|---:|---:|---:|---:|---:|---:|
| 1 | 100% | 0% | 0% | 0% | 0% |
| 2 | 100% | 0% | 0% | 0% | 0% |
| 3 | 75% | 25% | 0% | 0% | 0% |
| 4 | 55% | 30% | 15% | 0% | 0% |
| 5 | 45% | 33% | 20% | 2% | 0% |
| 6 | 30% | 40% | 25% | 5% | 0% |
| 7 | 16% | 30% | 43% | 10% | 1% |
| 8 | 15% | 20% | 32% | 30% | 3% |
| 9 | 10% | 17% | 25% | 33% | 15% |
| 10 | 5% | 10% | 20% | 40% | 25% |

| Custo | Cópias iniciais por campeão (`B_c`) | Campeões distintos | Total inicial da faixa |
|---:|---:|---:|---:|
| 1 | 30 | 14 | 420 |
| 2 | 25 | 13 | 325 |
| 3 | 18 | 14 | 252 |
| 4 | 10 | 14 | 140 |
| 5 | 9 | 10 | 90 |

Para Lux, formas diferentes compartilham a identidade da mesma unidade de custo 5 na pool; não contar cada forma como um campeão distinto. O mesmo princípio vale para formas alternativas de uma unidade, como Akali/Grompe/Kog'Maw, quando a identidade de compra é uma só.

## Fórmula da loja normal

Seja `u` o campeão alvo de custo `c`; `L` o nível **no instante da geração da loja**; `q[L,c]` a probabilidade da faixa de custo; `B[c]` o tamanho inicial da pool por campeão; `h[u]` o número de cópias do alvo fora da pool; `r[u] = max(0,B[c]-h[u])`; e `T[c] = soma(r[v] para todos os v de custo c)`.

Para **um espaço** da loja normal, enquanto a faixa ainda tem cópias:

```text
P(alvo u em um espaço | estado completo) = q[L,c] × r[u] / T[c]
```

Um campeão 2 estrelas representa 3 cópias físicas e um 3 estrelas, 9. Contar tabuleiro, banco e ofertas reservadas nas lojas **uma única vez por cópia física**; não multiplicar contagens por observações repetidas do mesmo avatar. Ao atualizar, as ofertas não compradas da loja anterior retornam à pool antes da nova geração no modelo existente. Se uma faixa esgotar, a distribuição de custos tem de ser normalizada sobre as faixas ainda disponíveis; isso exige confirmação da regra do servidor para todos os casos especiais.

### Cinco espaços sem fingir independência

O cálculo exato, condicionado à pool informada e a sorteios sem reposição dentro da loja, é uma recorrência. Seja `n=(T1,…,T5)`, `r` as cópias restantes do alvo, `s` os espaços por preencher, `F(n,r,s)` a chance de **não** encontrar o alvo e `a_k=q[L,k]/Σ_{j:n_j>0}q[L,j]`:

```text
F(n,r,0) = 1
F(n,r,s) = Σ_{k ≠ c} a_k F(n-e_k,r,s-1)
           + a_c (1-r/n_c) F(n-e_c,r,s-1)
P(pelo menos uma cópia em cinco espaços) = 1-F(n,r,5)
```

Essa é a lógica já implementada em `trainer/simulation/shop_probability.py` para a próxima loja ordinária com a pool fornecida. Para uma aproximação rápida quando a pool é grande, usar `1-(1-q[L,c]r/T[c])^5`; **não** usar essa aproximação quando a pool está muito reduzida, a loja tem slots forçados ou se quer várias cópias.

Exemplo de referência: no nível 8, um campeão de custo 4 intacto tem `r=10`, `T4=140`, logo chance por espaço `0,30×10/140≈2,14%` e chance aproximada na loja de cinco espaços `≈10,26%`. Se quatro cópias desse campeão saíram da pool e nenhuma outra unidade custo 4 mudou, `r=6`, `T4=136`: `≈1,32%` por espaço e `≈6,44%` na loja. Isso mostra por que observar o banco adversário importa.

Para várias lojas, atualizar `L`, `r`, `T`, efeitos, compras, vendas e lojas dos outros jogadores após cada evento. Só se o estado permanecer igual é válido usar `1-(1-p_loja)^m` para `m` lojas. Número de cópias até 2 ou 3 estrelas pede distribuição do total de sucessos e compras, não apenas probabilidade de ao menos uma ocorrência.

## Efeitos que exigem trocar a distribuição da loja

| Fonte | Regra para o cálculo |
|---|---|
| Fogo-Fátuo Tudo Um/Dois/Três/Quatro/Cinco | A loja gerada fica restrita à faixa indicada. Substituir `q[L,c]` por 100% nessa faixa e 0% nas outras, para a loja especial. |
| Fogo-Fátuo Cidade Inicial, Vilarejo Fronteiriço, Caminho Intermediário | Loja de custo fixo com ofertas de 2 estrelas. Cada oferta representa 3 cópias; usar o gerador especial, não cinco sorteios normais. |
| Fogo-Fátuo Grupo de Busca | Cada loja oferece uma unidade de custo 4 até comprar uma; o custo do efeito mudou no 18.4B. Modelar o(s) espaço(s) garantido(s) separadamente e parar no evento de compra. |
| Fogo-Fátuo Segue o Fluxo | As próximas lojas garantem unidades colocadas em campo no último combate; conjunto candidato condicionado ao tabuleiro anterior. |
| Fogo-Fátuo Boas-vindas à Selva e Fera do Rift (5) | Loja invadida por Feras do Rift; condicionar o conjunto de candidatos e a cadência ao efeito observado. |
| Inferno, no marco que incendeia a loja | Alguns slots sem Inferno são sorteados um tier acima; condicionar ao resultado e ao número de slots efetivamente afetados. |
| Dados Viciados | Loja especial filtrada por característica da unidade alvo; não aplicar as chances da loja normal sem identificar a característica elegível. |
| Aprimoramentos Loja Viciada+, Composição Máxima e Serviço de Assinatura | Lojas especiais: custo 3 forçado em certa cadência, próxima loja com cinco custos 4 únicos, ou loja de quatro custos 4 únicos por estágio. Precisam de distribuição própria e condições de ativação. |
| Avatar (Lux) | Se já possuir um Avatar no banco/tabuleiro, as outras ofertas de Avatar na loja mudam para a característica escolhida. Isso altera a **forma exibida**, não cria mais identidades de Lux na pool. |

Os nomes e resumos vêm das descrições da build 16.20. Algumas descrições contêm parâmetros internos sem valor resolvido; não inventar chances de ativação. Fogo-Fátuo aparece em toda outra loja, no espaço direito, e a unidade por trás fica visível depois da fase de planejamento; Florescer (5) coloca Fogo-Fátuo em toda loja e Florescer (9) permite comprar dois por rodada. Estágio 5 em diante condiciona a categoria dos Fogos-Fátuos. Essas regras afetam quantas oportunidades de loja são visíveis e quais efeitos especiais podem ser comprados, não devem ser confundidas com um sexto espaço permanente.

## Efeitos que mudam quantas lojas ou cópias se pode obter

- Ouro, juros, sequências de vitória/derrota, HP, custo de atualização, EXP, nível, rodada e orçamento definem **quantas** lojas cabem antes de um prazo. O estágio, sozinho, não substitui o nível na tabela `q`; ele aciona efeitos programados e altera a economia. Compras de EXP antes/depois de atualizar mudam as chances das próximas lojas.
- Aprimoramentos de atualizações gratuitas: Núcleo de Negócios, Setor Comercial, Troca Sem Fim, Bilhete Prismático, Maratona de Compras, Época/Era, Derrota Planejada, Investimento+, Quem Espera Sempre Alcança, Criação Engenhosa, entre outros. Usar sua condição, limite e duração observados, sem presumir que todo item listado no arquivo está habilitado.
- Teemo pode gerar atualização, EXP ou HP por cogumelos; sua chance e a cor do resultado não devem ser assumidas se não foram observadas. Draven/Caçador de Recompensas pode conceder atualizações e unidades; conferir missão/recompensa da partida.
- LeBlanc pode criar cópia de aliado ao fim do combate; a chance cresce com eliminações. Aprimoramentos Vale a Espera, Reserva de Pandora, Conexões Perdidas, Furto, Duplicadores, Polimorfia, carrossel e recompensas geram ou transformam unidades por canais **distintos**. Para achar `u` por qualquer meio: `P(u até o prazo)=1-P(não u em nenhum canal)`, calculado condicionalmente à sequência de estados, evitando somar probabilidades correlacionadas.
- Efeitos que dão ouro ou EXP aumentam oportunidades **indiretamente**. Efeitos que obrigam uma faixa/traço ou concedem unidade direta mudam o sorteio **diretamente**. Itens de combate e passivas sem geração de ouro, EXP, loja ou cópias não alteram as chances mecânicas de aparecer na loja, embora influenciem a estratégia e o resultado dos combates.

## Informação incompleta: o que mostrar ao usuário

O estado real da pool inclui bancos adversários, lojas atualmente abertas, compras, vendas e unidades criadas/transformadas por efeitos. Capturas não revelam tudo. Portanto:

1. Registrar `h_confirmado[u]` por rastreio único de cada peça em tabuleiro e banco; `3^(estrelas-1)` cópias por unidade confirmada. Guardar `h_oculto[u]` como intervalo ou distribuição, não como zero verdadeiro.
2. Calcular um intervalo de chance com cenários plausíveis para o estoque oculto, ou marginalizar por uma distribuição probabilística explícita `P(h_oculto | histórico)`. Mostrar premissas, patch, nível, estado da loja, número de ofertas e fonte da leitura.
3. Em replay, registrar cronologicamente mudanças de nível, lojas, compras, vendas, carrossel, cópias geradas, mortes de jogadores, efeitos e disponibilidade observada. Nunca usar o nível atual para inferir a probabilidade da **aquisição passada** de uma peça no tabuleiro.
4. Separar a **probabilidade de aparecer** da **probabilidade de identificar visualmente** uma peça. HP, itens, características, posição, nomes no cartão e rastreio temporal ajudam na identidade; não são multiplicadores da chance da loja. Combinar sinais visuais por fonte calibrada, sem contar pixels da mesma imagem duas vezes.

Próxima validação necessária: comparar a tabela 18.3B com a UI/cliente 18.4B; confirmar pool e semântica de retorno/duplicação por efeito; extrair parâmetros numéricos dos efeitos ativos; testar lojas normais e especiais em replay 1080p com telemetria legível. Até essa validação, o resultado deve aparecer como **estimativa condicionada**, não como probabilidade exata de uma partida real.

## Ação que muda o sorteio: além de um overlay

Contar cartas informa o risco, mas não altera o sorteio. O planejador deve comparar **ações disponíveis agora**, com o mesmo orçamento e horizonte: atualizar, comprar EXP primeiro, usar Fogo-Fátuo de custo forçado, ativar característica de loja, comprar um campeão concorrente do mesmo custo para reduzir temporariamente a pool, ou guardar recursos. Para cada ação `a`:

```text
valor(a) = P(completar o objetivo até a rodada limite | a, estado)
           × valor estratégico da melhoria
           - ouro/EXP/HP/juros gastos
           - custo de ocupar banco e de perder flexibilidade
```

Comparação ilustrativa para **uma cópia** de um custo 4, nível 8, pool intacta de 140 cópias com 10 do alvo:

| Ação / loja | Chance aproximada de ver o alvo | Interpretação |
|---|---:|---|
| Loja normal, cinco slots | 10,26% | Referência. |
| Segurar oito cópias de outros custos 4; próxima loja normal | 10,86% | Ganho inferior a 1 ponto percentual; costuma ser caro em ouro e banco. |
| Um slot garantido custo 4, quatro slots normais | 14,85% | Cenário matemático para avaliar efeito de slot garantido; confirmar implementação exata do efeito. |
| Cinco slots custo 4, sorteio sem reposição | 31,35% | Cenário de Tudo Quatro; melhora material, mas depende de obter o Fogo-Fátuo e pagar seu custo. |

Esses números são condicionais, não promessa de acerto. A vantagem concreta vem de **selecionar uma ação que altera a distribuição**, sobretudo lojas de custo forçado, em vez de apenas mostrar que a chance atual é 10%. Comprar campeões concorrentes da mesma faixa ajuda pouco em uma pool cheia; não recomendar isso automaticamente. O planejador deve avaliar as ações do patch que estejam realmente disponíveis na tela e mostrar também o preço de oportunidade.

Sem acesso ao estado oculto nem controle do sorteio aleatório, nenhum algoritmo pode garantir o campeão. A meta verificável é superar uma política de referência em replay/simulação pareada, medindo taxa de conclusão da unidade até a rodada limite, ouro restante e HP. Se não houver ganho mensurável, o recurso não deve ser apresentado como melhoria estratégica.
