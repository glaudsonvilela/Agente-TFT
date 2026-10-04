# Memória de estratégias e mecânicas sazonais

Pesquisa de **4 de outubro de 2026**, para **TFT Set 18, 18.3B com as desativações de 28/09**.

A memória estruturada está em [memory.json](../configs/training/strategy-memory/TFTSet18/18.3B-20260928/memory.json): 19 fontes, 15 grupos de mecânicas e 12 estratégias condicionais. Cada registro identifica procedência, estado necessário, dúvidas e alternativas a comparar. O inventário anterior das 36 características continua referenciado por caminho e SHA-256.

**Conhecimento salvo para pesquisa; pesos neurais não foram alterados. Nenhuma nova simulação foi executada nesta etapa.** O pacote executável ainda é 18.3 e não recebe silenciosamente números de 18.3B. Esta memória não é consumida pelo HUD como uma política pronta.

## Correções que mudam o resultado

As notas oficiais atuais prevalecem sobre a apresentação inicial do set e sobre guias:

- Blackthorn 6 ainda sacrifica a unidade. Implementar a descrição antiga produz um combatente extra indevido.
- Ivern começa com três **hexes**, não três sementes.
- Coven precisa de uma distribuição de recompensas; o exemplo de um guia não garante o mesmo item em toda retirada.
- A loja especial Riftbeast usa conjuntos correlacionados. Sortear cada slot pela probabilidade marginal produz lojas diferentes das descritas pela fonte.
- Dark Ritual e Major Polymorph não podem sustentar cenários do patch pesquisado.

Referências: [Riot 18.3 e hotfix](https://teamfighttactics.leagueoflegends.com/en-au/news/game-updates/teamfight-tactics-patch-18-3/), [Riot 18.2](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-2/), [tabela Riftbeast](https://www.tftraits.com/traits/riftbeast/). Os demais aprimoramentos desativados e os números pesquisados estão no JSON, com suas fontes.

## Estratégias a comparar

“Melhor” permanece uma pergunta condicionada ao estado observado. Não foi inferida taxa de vitória de opiniões ou tier lists.

| Família | Pergunta para o experimento |
|---|---|
| Ravager flexível | Qual abertura preserva mais vida com as peças disponíveis? |
| Blossom AP | Quando a transição compensa o custo de trocar unidades? |
| Veigar reroll | A chance de completar upgrades supera o custo de adiar níveis? |
| Kha’Zix cedo | Reroll ou transição quando há disputa pelas cópias? |
| Coven | Retirar a recompensa atual ou aceitar o risco de continuar? |
| Ashe/Draven | Subir para 9 ou estabilizar o tabuleiro no 8? |
| Solar/Lunar | Quantas cópias, recursos e espaço de banco tornam a linha viável? |
| Ahri Invoker | Melhorar unidades, poupar ou ajustar formação contra o adversário? |
| Nidalee/Aphelios | Qual bênção e distribuição de itens favorecem o horizonte restante? |
| Sivir/Nidalee | Qual frontline disponível e bênção produzem melhor resultado? |
| Azir/Rammus | Quanto o sacrifício e a permanência no nível 7 realmente entregam? |
| Riftbeast | Quando trocar a Marca Alfa ou parar de rolar para subir? |

As perguntas são propostas do projeto. As condições de entrada vêm dos guias identificados em cada registro. O [fluxograma de Wasianiverson/TFTAcademy](https://www.youtube.com/watch?v=k8EmL7emHoI) foi lido integralmente pela transcrição automática e teve um trecho visual conferido online. Não foi classificado como uma partida completa ou demonstração rotulada. Nomes transcritos incorretamente não viraram IDs ou fórmulas. Os guias de [Ahri](https://tftflow.com/composition/set18/invoker-ahri), [Azir](https://tftflow.com/composition/set18/rammus-azir), [Aphelios](https://tftflow.com/composition/set18/nidalee-aphelios), [Sivir](https://tftflow.com/composition/set18/sivir-nidalee) e [Riftbeast](https://tftflow.com/composition/set18/riftbeast-tempo) complementam as hipóteses.

## O que precisa existir antes da comparação

1. **Estado de partida e economia:** fases, XP, juros, sequências, banco, pool compartilhado e loja. Esses dados entram como pacote sazonal; coordenadas de captura continuam separadas.
2. **Wisps e lojas especiais:** elegibilidade, versão aprimorada, compra, expiração e ordem de execução entre Blossom, Inferno, Riftbeast e Lux.
3. **Estado persistente:** essência Coven, terreno de Ivern, bênçãos Primal, progressão Rival, missões Draven e Pixies. Fusão, venda e passagem de rodada precisam preservar ou limpar exatamente o que a regra determina.
4. **Combate das composições:** todas as habilidades, formas, itens, invocações e características presentes. Um spell implementado não torna sua composição simulável.
5. **Calibração independente:** cenas anotadas, resultados reais e verificação de interações. Tabelas de terceiros permanecem hipóteses quando semântica e unidade estão ambíguas.

Os 15 grupos pesquisados explicitam o estado e as lacunas. O [mapa integral](SIMULATOR_RULE_MAP.md) preserva as demais habilidades, características, itens, aprimoramentos, loot e sistemas ainda pendentes. Este documento não declara essas lacunas encerradas.

## Protocolo da próxima simulação

Primeiro verificar as dependências de cada cenário no patch exato. Em seguida comparar ações legais a partir do mesmo estado: rolar, comprar XP, guardar ouro, equipar ou preservar componentes, reposicionar e mudar a linha. Usar sementes emparelhadas e variar HP, itens, cópias, disputa e adversários; não fornecer à política informações ocultas que o jogador não possui.

Registrar resultados com horizonte explícito. Vitória em um combate não equivale a top 4 em uma partida. Reportar incerteza por partida independente, separar treino/avaliação por partida e evitar vazamento entre trechos do mesmo VOD. Contar buscas internas separadamente das partidas simuladas.

Uma dica futura precisa indicar ação e motivo, com validade temporal. “Role agora” exige avaliar custo e benefício no estado atual. Ao ficar estável, mudar de fase ou atualizar a leitura, o conselho deve ser reavaliado. O contrato e as métricas estão em `experiment_contract` no JSON; são critérios planejados, ainda não um motor integrado.
