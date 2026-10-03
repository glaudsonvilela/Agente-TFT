# B4 — primeiro sinal visual do inventário

O objetivo completo do hub é observar unidades, posição nas células, itens
equipados e itens no inventário. O B4 inicia pela faixa visual do inventário no
layout Match001 de 1920×1080. Ele registra presença de ícones, vazio aparente e
desconhecido, sem atribuir nomes nem atualizar `GameState`.

## Evidência disponível

O ensaio B3 nos mesmos 40 JPEGs gerou 148 caixas neurais, mas nenhum item,
identidade ou ponto no chão confirmado. A inferência CPU teve p50 de 8.311,5 ms
por imagem. Esses dados não justificam integrar o detector aberto ao loop ao vivo.

No B4, a faixa da esquerda foi inspecionada nos 40 JPEGs existentes. O primeiro
espaço mostra um ícone de pilha com contador e **não é tratado como item**.
Os nove espaços seguintes têm recortes interiores fixos neste perfil. A âncora
laranja do primeiro espaço precisa aparecer antes de interpretar os demais.
O algoritmo mede apenas a fração de pixels claros no recorte interno; a faixa
entre os limites de ícone e vazio produz `unknown`.

Resultado de desenvolvimento no mesmo lote, sem rótulos independentes:

- painel localizado em 37/40 imagens; três imagens de desktop/transição
  ficaram `unavailable`;
- nos 333 espaços elegíveis: 39 `icon_candidate`, 291 `empty_appearance`,
  três `unknown`;
- `item_id` permanece `null` em todos os espaços;
- nenhum resultado é promovido a inventário semântico ou decisão.

Essas contagens medem cobertura visual **neste replay**, não precisão de item.
As mesmas imagens serviram para escolher os limites. Um novo replay e rótulos
independentes são necessários antes de declarar acurácia ou ativação.

## Uso local

```bash
python3 -m training.board_hub_inventory \
  --profile configs/ui/match001-inventory-v1.json \
  --image /caminho/para/um/frame.jpg
```

O comando exige Pillow para abrir JPEG; a função `observe` e os contratos de
teste usam somente bytes RGB. A saída é uma observação diagnóstica JSON.

## Próximos gates

O catálogo visual oficial pode ser atualizado sem editar coordenadas:

```bash
python3 -m ingestion.riot_ddragon_reference \
  --version 16.19.1 --locale pt_BR --set TFTSet18
```

O comando busca os JSONs oficiais de campeões e itens do Data Dragon, registra
hashes dos bytes de origem e cria uma referência imutável em
`knowledge/riot-ddragon/`. Campeões são filtrados pelo set explícito; itens
preservam o escopo amplo do provedor. A versão Data Dragon **não prova** o patch
TFT da gravação; por isso `tft_patch=null` e `replay_binding=false`. O Match001
continua com set/patch desconhecidos. A release CommunityDragon existente pode
ser usada como segunda fonte quando seu set/patch for comprovado, sem misturar
IDs de provedores por nome.

O snapshot versionado `16.19.1/pt_BR/TFTSet18` contém 74 retratos de campeões
do set selecionado e 1.188 entradas de itens de escopo amplo. É um **banco de
referência**, não uma lista inferida dos 40 frames. O replay serve para ensaiar
o leitor e revisar candidatos dos poucos ícones visíveis nele.

```bash
python3 -m training.board_hub_item_candidates \
  --reference knowledge/riot-ddragon/16.19.1/pt_BR/TFTSet18/5dafba7d15d09fb77b4ba83af78f3a46f0986121f68c46e3be6bf41da85c823f \
  --profile configs/ui/match001-inventory-v1.json \
  --image /caminho/para/um/frame.jpg \
  --icon-dir /caminho/para/cache-de-icones --fetch-missing
```

O cache de PNGs é local. O leitor relata sua cobertura e os downloads que
falharam; `item_id` permanece nulo em todos os casos nesta etapa. Cada
candidato traz a distância visual e a margem
para o segundo desenho. São pontuações de similaridade, não probabilidades
calibradas. Um teste nos 40 frames não mede cobertura de itens que não aparecem
na gravação. A versão visual do Data Dragon ainda precisa ser vinculada ao
patch TFT comprovado antes de alimentar `GameState`.

## Posições candidatas no tabuleiro

`training.board_hub_position_candidates` usa as barras verdes do relatório B1
e o perfil visual `match001-bar-to-cell-candidates-v1` para sugerir linha e
coluna da grade 4×7 ou espaço do banco. As faixas verticais e o limite de
distância horizontal são dados do layout, fora do catálogo de patch. A saída
mantém `ground_point`, `occupancy` e `unit_id` nulos; não afirma que a arena
vista é a do próprio jogador.

No desenvolvimento com os 40 frames Match001, 17 projeções de arena foram
aceitas pelo B1 e 23 permaneceram indisponíveis. Nas 17, o mapeamento produziu
76 posições candidatas no tabuleiro e 12 no banco; nove barras vermelhas e
sete marcadores fora das faixas ficaram sem atribuição. No frame 27, os oito
marcadores do tabuleiro caíram em cinco células da linha 0, uma da linha 1 e
duas da linha 3; o nono caiu no primeiro espaço do banco. São contagens do
mesmo replay usado para ajustar as faixas, não precisão validada.

```bash
python3 -m training.board_hub_position_candidates \
  --report /caminho/para/board-b1/report.json \
  --board-profile configs/ui/match001-board-bench-v1.json \
  --projection-profile configs/ui/match001-bar-to-cell-candidates-v1.json
```

## Itens equipados abaixo das barras

`training.board_hub_equipped_candidates` examina três espaços abaixo de cada
barra verde aceita pelo B1. A saída liga os recortes ao `marker_id` e à célula
candidata; `unit_id` e `item_id` continuam nulos. O parâmetro
`--match-scope set_path` usa apenas as entradas cujo caminho oficial começa
com `TFTSet18/`: são 156 imagens neste snapshot, enquanto o banco original
preserva as 1.188 entradas. Essa seleção por caminho é uma hipótese explícita
para o set, não prova de patch nem garantia de que todos os itens jogáveis
estejam nesse prefixo.

No mesmo lote Match001, nas 17 imagens com arena localizada, houve 48 recortes
`icon_candidate`, 150 `empty_appearance` e 87 `unknown`. No frame 27, seis
recortes aparecem sob três barras e os seis foram marcados como candidatos;
os nomes mais próximos incluem Placa Gargolítica, Capa de Fogo Solar, Bastão
Desnecessariamente Grande, Morellonomicon, Lâmina Mortal e Fúria do Cráquem
no catálogo selecionado. A
similaridade foi ajustada e conferida neste replay, sem medição independente
de acurácia, e ainda não identifica qual campeão carrega o item.

```bash
python3 -m training.board_hub_equipped_candidates \
  --reference knowledge/riot-ddragon/16.19.1/pt_BR/TFTSet18/5dafba7d15d09fb77b4ba83af78f3a46f0986121f68c46e3be6bf41da85c823f \
  --icon-dir /caminho/para/cache-de-icones \
  --image /caminho/para/frame-27.jpg --report /caminho/para/board-b1/report.json \
  --frame-index 27 --board-profile configs/ui/match001-board-bench-v1.json \
  --position-profile configs/ui/match001-bar-to-cell-candidates-v1.json \
  --equipped-profile configs/ui/match001-equipped-icons-v1.json \
  --match-scope set_path
```

## Visão única por frame

`training.board_hub_snapshot` reúne as 28 células fixas, nove espaços do banco,
marcadores de unidade, candidatos de itens equipados e inventário em um JSON.
Ele exige que o timestamp no nome do JPEG corresponda ao frame do relatório
B1 para impedir associações entre imagens diferentes. No frame 27, a saída
contém nove marcadores (oito de tabuleiro e um de banco), seis ícones equipados
candidatos e um ícone candidato no inventário. `champion_id`, `item_id` e
ocupação confirmada ficam nulos; o JSON relata essas capacidades ausentes.

```bash
python3 -m training.board_hub_snapshot \
  --image /caminho/para/0027_001300000ms.jpg \
  --report /caminho/para/board-b1/report.json --frame-index 27 \
  --board-profile configs/ui/match001-board-bench-v1.json \
  --position-profile configs/ui/match001-bar-to-cell-candidates-v1.json \
  --equipped-profile configs/ui/match001-equipped-icons-v1.json \
  --inventory-profile configs/ui/match001-inventory-v1.json \
  --reference knowledge/riot-ddragon/16.19.1/pt_BR/TFTSet18/5dafba7d15d09fb77b4ba83af78f3a46f0986121f68c46e3be6bf41da85c823f \
  --icon-dir /caminho/para/cache-de-icones
```

Fonte oficial: https://developer.riotgames.com/docs/tft#data--assets

1. Criar anotações verificadas de espaços/itens de um replay distinto.
2. Reconhecer o ícone pelo catálogo do set/patch, preservando `unknown` quando
   houver ambiguidade, contador ou item fora do catálogo.
3. Localizar base da unidade e validar associação à célula; identificar
   campeão e estrelas em amostras independentes.
4. Detectar os ícones equipados e associá-los à mesma instância de unidade.
5. Confirmar temporalmente a transição inventário → unidade antes de preencher
   `GameState` e liberar recomendações de item/posicionamento.
