# Auditoria dos Aprimoramentos — Conjunto 18

**Escopo:** verificar se o catálogo e as observações do Motor 1 já podem
alimentar treino de decisões. Resultado: **ainda não**. O leitor pode coletar
ofertas e recortes; escolha e resultado permanecem sem confirmação.

## Dados conferidos

| Fonte | Cobertura constatada | Limite |
| --- | ---: | --- |
| Catálogo anterior (`DA_`, Data Dragon 16.19.1) | 249 IDs | Excluía IDs citados nas notas do patch 18.4. |
| Arquivo Data Dragon 16.20.1 | 758 IDs | Aprimoramentos não heroicos de conjuntos ativos; não é a lista de ofertas desta partida. |
| Lista de IDs do cliente Set 18 (espelho CommunityDragon 16.20) | 592 IDs | 590 estão no Data Dragon atual; dois só constam do cliente. Inclui nomes sem provar elegibilidade. |
| Suplemento preservado | 4 IDs | Dois ausentes do Data Dragon atual e dois removidos desde 16.19.1. |
| Busca do leitor | 762 IDs distintos | União dos 758 atuais com quatro históricos/omitidos; não equivale ao total de cartas elegíveis. |
| Prefixo `DA_` em 16.20.1 | 249 IDs | Dois IDs entraram, dois saíram frente a 16.19.1. |
| Diferença entre versões | 21 registros brutos | Após remover mudanças só de formatação: quatro descrições e um ícone mudaram. |

Entre os IDs omitidos pelo filtro `DA_` estavam
`TFT_Augment_ConstructACompanion` e `TFT_Augment_ForgeAFriend`, ambos
mencionados como reativados nas [notas oficiais do 18.4](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/).
As mesmas notas mencionam *Challenger’s Grace*, que não aparece nem no arquivo
Data Dragon 16.20.1. Por isso os 758 registros **não comprovam cobertura de
todas as cartas do jogo**. A [documentação da Riot](https://developer.riotgames.com/docs/tft)
descreve o arquivo como fonte de Aprimoramentos não heroicos; ele não identifica
sozinho a elegibilidade de cada carta na partida.

Comparei ainda os IDs do cliente 16.20 no
[espelho CommunityDragon](https://raw.communitydragon.org/16.20/cdragon/tft/en_us.json).
Ele contém 592 IDs associados ao Conjunto 18; os dois ausentes do Data Dragon
atual são `DA_ChallengersGrace` e `TFT_Augment_BoosterPackPlusPlus`.
Preservei também `DA_NestingDollsPlus` e `DA_NestingDollsPlusPlus` do Data
Dragon 16.19.1, retirados da versão atual após a desativação temporária de
*Matrioscas* registrada nas [notas oficiais do 18.3B](https://teamfighttactics.leagueoflegends.com/pt-br/news/game-updates/teamfight-tactics-patch-18-3/).
Esses quatro IDs estão no suplemento de referência e são reconhecíveis pelo
leitor, mesmo quando não forem oferecíveis. O espelho do cliente ainda mostra
3 s para *Graça de Desafiante*; a descrição do suplemento usa os 4 s das
notas oficiais 18.4B. O status atual dessa carta não foi confirmado.

As notas oficiais também registram regras que o arquivo não deve substituir:
*Heart of Steel* foi temporariamente desativado no 18.4B; *Makeshift Armor I/II*
não aparece em 2-1; *Chosen of the Sun* mudou de Ouro para Prata. *Coven
Acolyte* e *Dark Ritual* dividem o limite de uma escolha por lobby; *Chosen of
the Sun* também tem limite de uma escolha por lobby. A atualização 18.4B ainda
alterou valores de vários Aprimoramentos, inclusive *Challenger’s Grace*.
Essas restrições e valores precisam ser verificados contra o patch real antes
de treinar probabilidades ou avaliar escolhas.

Como contraprova de cobertura, a [lista de terceiros SeeMeta para
18.4](https://seemeta.com/en/tft/set-18/augments) mostra 249 cartas e inclui
*Challenger’s Grace*, ausente do Data Dragon consultado. Ela também lista
*Heart of Steel*, embora a Riot informe que está desativado temporariamente
em 18.4B. Portanto a lista ajuda a descobrir lacunas, mas também não prova
quais cartas estão elegíveis agora.

## Ligação com a partida

O vídeo `gameplay.mp4` tem data de criação 2026-10-12 02:01:49 UTC, após o
lançamento do 18.4B, mas não há número de patch confirmado pelo cliente no
material examinado. A captura fornecida mostra três ofertas em 2-1: Estudo
Paciente, Vigarista e Acólito da Congregação das Bruxas. Os dois primeiros
nomes aparecem com IDs legados e `DA_` quase idênticos no arquivo; a imagem
confirma nome e efeito, mas não resolve o ID de origem. O terceiro tem um ID
único no arquivo.

O Motor 1 agora preserva o texto OCR e todos os IDs candidatos, grava um evento
de oferta e salva a imagem do quadro e os três recortes quando vê um conjunto
novo de cartas. Esses pixels são **evidência sem rótulo de verdade**. Não foi
executada uma sessão nova com esse leitor até esta auditoria. Nenhuma escolha
do jogador ou colocação final foi confirmada, portanto ainda não existe uma
linha `ofertas → escolhida → resultado` válida para treino supervisionado.

## Estado para treino

- **Leitura das ofertas:** implementada; comprovada na captura fornecida.
- **Arquivo de referência:** 762 IDs distintos, incluindo os quatro itens
  omitidos ou arquivados; cobertura da lista oferecível permanece não verificada.
- **Patch da partida:** provável 18.4B pela data, não confirmado pelo cliente.
- **Carta escolhida:** não observada de forma confiável.
- **Resultado da escolha:** não ligado à oferta.
- **Treino de política:** bloqueado por falta dos dois rótulos anteriores.

Contagens e IDs da diferença estão no
[`augment-catalog-audit-20261011.json`](augment-catalog-audit-20261011.json).
