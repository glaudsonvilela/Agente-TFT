# Modelo macro da partida — TFT Set 18, patch 18.4B

Pesquisa de 2026-10-11. Este modelo precede qualquer recomendação de reroll, item ou hexágono. Ele reconstrói uma **partida com até oito jogadores** e representa explicitamente o que ainda não foi observado. O cálculo de uma loja é um submódulo, não o estado inteiro do jogo.

## Fontes e limites

- [Riot: pool compartilhada, scouting e contestação](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-13-23-notes/): a Riot descreve esses fatores como a base das decisões de rolar.
- [Riot: Enchanted Wilds](https://teamfighttactics.leagueoflegends.com/en-sg/news/game-updates/enchanted-wilds-overview/): características e Fogos-Fátuos que alteram economia, tabuleiro e lojas; Florescer, Fera do Rift, Coven, Teemo e LeBlanc.
- [Riot: 18.4/18.4B](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/): regras de balanceamento atuais. O valor de um tabuleiro e de uma sinergia muda com o patch; não reutilizar pesos de 18.3B como se fossem 18.4B.
- [Riot: 18.3](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-3/): mudança da essência de Coven em derrotas e correção da Reserva de Pandora; demonstra por que o histórico de efeitos importa.
- O catálogo local de 65 unidades por custo está em `champion-reset-20261009/experiments/combined-dino-corpus-20261011/source/roster/all-65.json`. A pesquisa sobre a loja normal e seus parâmetros provisórios está em `docs/evidence/shop-probability-set18-18.4b-20261011.md`.

## 1. Estado global em cada instante

Para cada jogador `i ∈ {1,…,8}`, manter:

```text
Jogador_i = {
  vivo, HP, nível, EXP, ouro estimado/observado, sequência de vitória/derrota,
  unidades no tabuleiro, unidades no banco, estrelas, posições,
  itens e componentes, características ativas, Aprimoramentos,
  Fogos-Fátuos/efeitos ativos, ofertas observadas, últimas compras/vendas,
  provável direção de composição, próxima ameaça de eliminação
}
```

Cada peça tem `jogador`, `identidade` ou conjunto de candidatos, `estrelas`, `zona`, `slot`, `itens`, `primeira/última observação`, `confiança` e `fonte`. Um `track_id` estável impede que cinco capturas da mesma peça virem cinco unidades. Peças invocadas por características/combate são entidades do tabuleiro, mas **não** consomem automaticamente cópias da loja. Guardar `desconhecido` quando o banco rival não estiver visível; não substituir por vazio.

O estado global também inclui `estágio/rodada/fase`, carrossel e eventos, capacidade das pools, calendário de efeitos, janela até a próxima luta, e identidade dos jogadores. `HP`, estágio, nível, ouro, sequências, itens e características entram juntos: eles determinam urgência, recursos, força relativa e rotas de composição. Somente o nível alimenta a tabela base de custos da loja; o estágio atua por economia e gatilhos do conjunto.

## 2. Contabilidade simultânea de todas as 65 pools

Para cada campeão comprável `u`, com estoque inicial `B_u`, contar as cópias físicas confirmadas:

```text
H[i,u] = soma(3^(estrelas_da_peça-1)) das peças de u
         no tabuleiro e no banco do jogador i
```

Uma unidade 1/2/3 estrelas corresponde a 1/3/9 cópias. Uma unidade de 4 estrelas exige tratar 27 cópias físicas **ou registrar a exceção específica que a criou**; não inferir automaticamente 27 unidades retiradas da pool por um efeito especial. Formas visuais alternativas da mesma unidade devem partilhar uma identidade de pool. Depois, para a loja ordinária:

```text
R[u] = B_u - Σ_i H[i,u] - Σ_i Q[i,u] - C[u] + G[u]
```

`Q` são cópias reservadas em lojas ainda abertas, `C` outros reservatórios temporários confirmados (por exemplo, evento especial), e `G` é o ajuste **registrado por mecanismo** para cópias criadas fora da pool ou reintroduzidas. Não se pode presumir que todo efeito cria ou retira cópias da mesma forma. Sem comprovação da semântica de um efeito, deixar `G/C` incertos e não apresentar `R` como número exato. Para observações parciais, guardar um **intervalo viável** `R_min[u] ≤ R[u] ≤ R_max[u]` e/ou cenários ponderados.

Essa contabilidade permite conclusões fortes sem prever RNG. Para um objetivo de `s` estrelas, `precisa_u=max(0,3^(s-1)-H[eu,u])`. Se `R_max[u] < precisa_u`, o objetivo **não pode ser concluído pela loja normal enquanto esses adversários retiverem as unidades**, mesmo que a porcentagem nominal por nível pareça boa. Vendas, eliminação de jogadores e efeitos que criem cópias podem alterar essa conclusão depois.

Exemplo: uma unidade de custo 4 tem estoque de trabalho `B=10`. Se eu possuo seis cópias e adversários confirmadamente possuem três, resta no máximo uma cópia da pool. Para chegar às nove cópias de 3 estrelas faltam três. A rota da loja normal está bloqueada no estado atual; insistir em rolar por ela é erro macro.

## 3. Estado parcialmente observável e atualização temporal

O jogo completo não está na tela. Representar hipóteses sobre as unidades, bancos e recursos ocultos por `b_t(S)=P(S_t=S | O_1,…,O_t)`, em vez de preencher lacunas com zero. A cada evento/captura:

```text
b_t(S) ∝ P(O_t | S) × Σ_{S'} P(S | S', A_{t-1}, regras_18.4B) b_{t-1}(S')
```

`O_t` inclui leitura da tela, nome do jogador, HP, itens, estrelas, lojas, transições de características e rastreio temporal. `A_{t-1}` inclui compras, vendas, EXP, atualização, combate, carrossel, Aprimoramentos e efeitos. Rivais escolhem suas próprias ações: o modelo usa cenários de ação adversária, não assume que ficarão parados. Sinais visuais correlacionados da mesma imagem não devem ser multiplicados como evidências independentes. Uma peça vista antes pode mudar de tabuleiro/banco, ser vendida ou voltar à pool; preservar o evento e o momento.

Antes de aplicar probabilidades, aplicar **restrições duras**: peças observadas e confirmadas, custo/estrelas/capacidade, identidade de pool, número máximo de jogadores, posição, fase e efeitos conhecidos. Leituras incompatíveis vão para revisão; um palpite de nome não deve violar uma contagem confirmada da pool.

## 4. Diagnóstico macro por rodada

O estado estimado deve responder, para **todos** os jogadores:

1. Quem possui cada campeão e quantas cópias físicas, separando tabuleiro, banco, loja e desconhecido?
2. Quais unidades estão disputadas? Quem parece comprometido com a mesma composição, conforme peças/itens/características **verificados**?
3. Quem está forte ou vulnerável **agora** por HP, estrelas, tabuleiro, itens e efeitos? Como isso pode mudar nas próximas rodadas?
4. Quem pode subir de nível ou rolar mais cedo? Qual sequência, ouro observado/estimado e efeito econômico sustenta isso?
5. Qual objetivo meu ainda é viável com o estoque e horizonte restantes? Que composição alternativa usa unidades menos contestadas e itens já possuídos?
6. Qual o próximo confronto plausível, e qual informação adicional sobre um rival poderia mudar uma decisão?

Para uma ação macro `a` — rolar, subir nível, preservar economia, mudar composição, usar efeito, manter item flexível, fazer scouting — comparar cenários da partida inteira:

```text
Q(b_t,a) = E[ utilidade de colocação/HP/economia/flexibilidade
             ao longo do horizonte | b_t, a, ações possíveis dos rivais ]
```

A saída deve mostrar **restrições e cenários**, não uma vitória percentual inventada. A utilidade final pode privilegiar top 4, vitória ou sobrevivência conforme a preferência declarada, mas pesos e probabilidade de combate exigem calibração em partidas reais. O simulador atual é parcial; não chamar seu placar de `P(vencer)` antes dessa validação. Um adversário com HP baixo e tabuleiro forte, por exemplo, não deve ser classificado apenas pelo HP.

Scouting deve ocorrer pelo **valor da informação**, não por rotina cega:

```text
VOI(rival) = E_observação[max_a Q(b após observar rival,a)]
             - max_a Q(b atual,a) - custo de observar
```

Priorizar observar o jogador cuja bancada/tabuleiro pode mudar a escolha entre perseguir uma unidade e pivotar. Se um banco rival estiver oculto, a saída deve dizer que a recomendação depende de observá-lo.

## 5. Regras 18.4B com efeito macro

- **Pool compartilhada:** a concorrência entre os oito jogadores altera viabilidade de estrelas e janelas de compra. Ao eliminar/vender, reavaliar disponibilidade conforme a regra observada.
- **Florescer:** Fogos-Fátuos fortalecidos e maior frequência de ofertas em marcos da característica; muda rota econômica e a loja de cada rodada.
- **Fera do Rift (5):** lojas invadidas em certa cadência; muda acesso a uma família inteira de unidades.
- **Inferno:** slots incendiados podem oferecer unidade de custo superior; altera rotas de acesso a unidades caras.
- **Coven:** essência vem de eliminações e derrotas; sequência de derrotas pode ter valor econômico, mas consome HP e deve ser avaliada junto ao risco de eliminação. Os valores foram alterados em 18.3 e recompensas em 18.4.
- **Teemo, LeBlanc, Draven e Aprimoramentos:** podem conceder atualizações, cópias, XP ou ouro por meios diferentes. Tratar cada efeito como transição do estado, não como simples multiplicador das chances da loja.
- **Lux/Avatar:** formas da mesma campeã não contam como pools separadas; ofertas podem mudar de característica por posse de Avatar.

## 6. Caminho de implementação e medição

O projeto já possui `trainer/simulation/state.py`, que representa até oito jogadores e a pool, e `trainer/simulation/shop_probability.py`, que calcula a próxima loja normal quando a pool é fornecida. `apps/hud_mapper/hm/champion_belief.py` usa apenas cópias visíveis/confirmadas. `apps/hud_mapper/hm/opponent_tracking.py` acompanha principalmente nome e HP, e declara `opponent_board_assigned=False`; ainda falta atribuir com segurança tabuleiro e banco a cada rival. `apps/hud_mapper/hm/strategic_coach.py` exige estado próprio completo e rejeita vários efeitos sazonais. Portanto, **não há hoje um motor macro ao vivo completo**.

### Gargalo observado: inventário dos rivais

Uma inspeção do replay `champion-reset-20261009/experiments/full-hud-readiness-20261010/replay-cyber-both-sides-600s-1080.mp4`, perto de 325 segundos, mostra um combate com o nome do adversário, peças no tabuleiro superior e peças no banco superior. Esses pixels são uma fonte **potencial** de contagem para esse adversário naquele instante; a imagem não revela, ao mesmo tempo, os bancos dos outros seis rivais nem as lojas privadas deles. No código atual, `spatial_map.py` nomeia as casas e tenta ligar detecções ao banco inimigo, porém deixa ocupação e identidade como `unknown`/`unverified_detection`; `opponent_tracking.py` mantém a associação de dono como candidata. Logo, a falha principal é de **coleta e associação de observações**, anterior à fórmula da pool.

Protocolo necessário para o modo ao vivo: durante a preparação, registrar uma visita a cada adversário ainda vivo por sua linha do placar; capturar nome/HP e o tabuleiro+banco completos na mesma visita; ligar esses dados ao identificador estável do jogador; confirmar identidade e estrelas das peças por OCR do painel da unidade ou observações visuais repetidas; marcar hora/rodada da leitura. Quando a fase terminar, dados não revisitados envelhecem e voltam a ser intervalos, porque o rival pode comprar, vender ou combinar peças. Usar o combate apenas como observação adicional do rival enfrentado, não como substituto para visitar todos. A loja privada de cada rival permanece oculta e deve ficar como incógnita. Em um vídeo passivo que não visita determinado rival, não há algoritmo capaz de reconstruir com certeza o banco dele.

Ordem de construção e validação:

1. Registro temporal dos oito jogadores, tabuleiros, bancos, lojas, estrelas, itens, HP, nível e eventos, com `observado / inferido / desconhecido` e idade de cada leitura.
2. Contabilidade única das 65 pools, com formas agregadas e efeito especial registrado. Testar invariantes de cópia e impossibilidade, inclusive quando um rival vende ou é eliminado.
3. Cenários de economia, força relativa e contestação por rodadas; separar dados observados de hipóteses sobre planos dos adversários.
4. Simulação curta de decisões macro e valor de scouting; só depois conectar fórmulas de loja, itens, posicionamento e combate.
5. Replays completos em 1080p e avaliação contra políticas simples. Medir cobertura correta dos oito jogadores, erro em estrelas/cópias, taxa de recomendações inválidas e decisões que mudaram após scouting. Nenhum ganho estratégico é declarado sem comparação controlada.

Esta especificação é a prioridade arquitetural. Ela substitui a ideia de usar uma porcentagem isolada de loja como representação do jogo.
