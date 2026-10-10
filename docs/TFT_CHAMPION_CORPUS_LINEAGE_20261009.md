# Auditoria da origem dos dados de campeões — 09/10/2026

## Resultado

O software instalado carrega pesos treinados com **664 recortes**. Os **32 recortes** citados antes são apenas a validação, não o tamanho do treino. Os treinos anteriores de 04–05/10 aparecem na base ativa: 642 recortes mapeáveis a anotações de 16 grupos de origem, mais 22 recortes manuais de Xayah da mesma origem. Os vídeos novos de 08–09/10 **não entraram nos pesos instalados**.

O SHA-256 do `champions.onnx` instalado é `1045ffa3d75a76147b7314c90ecff247c7568cfb8a9187249837b37be0e391b4`, idêntico ao de `yolo-baseline/hud-readers-experiment/champion-names/weights/best.onnx`. O experimento aponta para `champion-classification-board-bench-dataset` (664 treino, 32 validação, 137 teste). Os candidatos posteriores não foram instalados.

Correção de 09/10: o usuário identificou como **Azir** o recorte de hash `255d90a52de0dfe424868fa0b18ac1b7c11ffa3c7f0ec350480f4e6d6bd03636`, vindo de `aou9H4gyQ1g` aos 594,6 s. Ele havia entrado no conjunto misto como Kha'Zix. O pacote principal de 731 imagens agora o armazena sob Azir, e a rotina de montagem aplica a correção pelo hash. Os conjuntos e pesos históricos não foram reescritos: o peso ativo antecede esse recorte; o candidato de 731 imagens foi treinado com o rótulo incorreto e não deve ser promovido. A revisão numerada dos demais recortes duvidosos está no SSD em `diagnostics/champion-image-forensics-20261009/identity-review/`.

## Inventário e proveniência

| Material | Situação |
| --- | --- |
| Base ativa: 664/32/137 | Rótulos de revisão visual assistida, sem verdade independente; três identidades foram contestadas depois |
| Novos recortes: 23 de nove vídeos | Rótulos de revisão visual assistida; entraram só no candidato de 684/32/137 |
| Extensão de outra origem: +47 | Revisada visualmente, mas de uma única fonte Twitch; gerou candidato separado de 711/32/137, não instalado |
| Capturas recentes: 41 vídeos direcionados, 2 YouTube e 1 Twitch, cerca de 32,6 GB de vídeo | São fontes sem rótulos de identidade suficientes para treino supervisionado automático |
| Experimento de quatro horas: 5.858 imagens de treino | Rótulos fracos gerados por modelo; não são verdade verificada |
| `bench-focus` | Caixas de unidades na reserva, sem nomes (`identity_labels: false`) |

O manifesto recente tem 24 caixas revisadas, mas só 23 recortes exportados: Draven ficou fora. O candidato de 684 excluiu três rótulos conflitantes; o peso ativo e a extensão de 711 herdam esses conflitos. Os 27 `match_group` do arquivo de anotações são grupos de origem/revisão, **não IDs de partidas comprovados**. A inclusão manual de Xayah usa uma mesma origem no treino (22 recortes) e no teste (10), portanto esse teste não é independente para Xayah.

## Origem por grupo revisado

Os grupos abaixo são os que efetivamente alimentaram o conjunto do modelo instalado. A mesma origem pode conter momentos correlacionados; grupos não são partidas independentes comprovadas.

| Divisão | Grupo anotado | Recortes | Classes |
| --- | --- | ---: | ---: |
| train | `manual-xayah-single-source` | 22 | 1 |
| train | `match-1f0938fe` | 23 | 6 |
| train | `match-6f784a17` | 73 | 13 |
| train | `match-9acfd9af` | 13 | 5 |
| train | `twitch-v2891050468-long-review` | 110 | 34 |
| train | `twitch-v2891050468-roster-10170` | 17 | 9 |
| train | `twitch-v2891050468-roster-1200` | 31 | 19 |
| train | `twitch-v2891050468-roster-13185` | 13 | 10 |
| train | `twitch-v2891050468-roster-4780` | 12 | 9 |
| train | `twitch-v2891050468-roster-6600` | 2 | 2 |
| train | `twitch-v2891052706-entire-source` | 78 | 39 |
| train | `youtube-CQhg2_6tzcM-entire-source` | 8 | 1 |
| train | `youtube-Jmi5fbZiFGU-entire-source` | 41 | 12 |
| train | `youtube-T0KVjZtR3GY-entire-source` | 44 | 10 |
| train | `youtube-UcztPIRD1m0-entire-source` | 57 | 24 |
| train | `youtube-bJF34u5fkGw-entire-source` | 30 | 13 |
| train | `youtube-nxSUNW1yZqI-entire-source` | 90 | 17 |
| val | `match-c39eced3` | 3 | 2 |
| val | `youtube-af1zvuCmr58-roster-11400` | 5 | 5 |
| val | `youtube-af1zvuCmr58-roster-15900` | 8 | 6 |
| val | `youtube-af1zvuCmr58-roster-4200` | 5 | 5 |
| val | `youtube-af1zvuCmr58-roster-600` | 1 | 1 |
| val | `youtube-af1zvuCmr58-roster-9900` | 10 | 9 |
| test | `manual-xayah-single-source` | 10 | 1 |
| test | `match-d75a3fcf` | 10 | 4 |
| test | `twitch-v2883698368-entire-source` | 98 | 38 |
| test | `twitch-v2890208196-episode-10500` | 2 | 2 |
| test | `twitch-v2890208196-episode-4500` | 8 | 5 |
| test | `twitch-v2890208196-episode-6900` | 9 | 8 |

## Cobertura dos 65 nomes

As 65 classes incluem criaturas neutras além de campeões. `Grupos` conta grupos de origem com algum recorte da classe no treino ativo; não garante partidas distintas. `Candidato 684` e `Extra 47` são conjuntos separados, que não podem ser somados sem revisão de sobreposição e conflitos.

| Nome | Treino ativo | Grupos | Val. | Teste | Candidato 684 | Extra revisão |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ahri | 11 | 6 | 0 | 1 | 11 | 0 |
| Akali | 11 | 3 | 1 | 3 | 11 | 1 |
| Alistar | 14 | 4 | 0 | 2 | 14 | 0 |
| Alune | 13 | 3 | 0 | 0 | 13 | 0 |
| Amumu | 4 | 4 | 1 | 7 | 5 | 1 |
| Aphelios | 8 | 3 | 0 | 4 | 8 | 0 |
| Aronguejo | 6 | 4 | 0 | 1 | 6 | 3 |
| Ashe | 11 | 5 | 0 | 2 | 11 | 1 |
| Azir | 7 | 3 | 1 | 2 | 6 | 0 |
| Azuporã | 12 | 5 | 0 | 2 | 12 | 2 |
| Caitlyn | 12 | 3 | 1 | 3 | 12 | 2 |
| Camille | 29 | 5 | 3 | 8 | 29 | 2 |
| Cascalho | 17 | 2 | 2 | 2 | 17 | 0 |
| Cassiopeia | 19 | 6 | 0 | 7 | 19 | 1 |
| Diana | 13 | 5 | 0 | 3 | 13 | 2 |
| Dragão Ancião | 2 | 1 | 0 | 0 | 3 | 0 |
| Draven | 8 | 2 | 0 | 0 | 8 | 0 |
| Elise | 10 | 2 | 1 | 1 | 10 | 0 |
| Ezreal | 15 | 5 | 0 | 1 | 15 | 2 |
| Fiddlesticks | 13 | 4 | 2 | 3 | 13 | 0 |
| Gnar | 15 | 5 | 0 | 0 | 15 | 1 |
| Grompe | 10 | 4 | 0 | 1 | 10 | 1 |
| Hecarim | 12 | 4 | 1 | 0 | 12 | 0 |
| Ivern | 7 | 3 | 0 | 1 | 7 | 0 |
| Karma | 12 | 1 | 0 | 2 | 12 | 0 |
| Kayle | 1 | 1 | 0 | 1 | 12 | 0 |
| Kennen | 15 | 3 | 0 | 3 | 15 | 0 |
| Kha'Zix | 1 | 1 | 1 | 0 | 2 | 1 |
| Kobuko | 9 | 4 | 1 | 0 | 9 | 0 |
| Kog'Maw | 19 | 5 | 0 | 2 | 19 | 2 |
| Krugue | 8 | 4 | 0 | 1 | 8 | 1 |
| LeBlanc | 16 | 4 | 0 | 1 | 16 | 0 |
| Leona | 10 | 3 | 0 | 3 | 10 | 0 |
| Lillia | 13 | 3 | 0 | 0 | 13 | 0 |
| Lobo Trevoguari | 2 | 2 | 1 | 0 | 6 | 0 |
| Lux | 8 | 1 | 0 | 0 | 8 | 0 |
| Malphite | 5 | 4 | 1 | 0 | 5 | 0 |
| Mamãe Bicuda | 7 | 1 | 0 | 1 | 7 | 0 |
| Maokai | 7 | 4 | 0 | 1 | 7 | 0 |
| Master Yi | 3 | 1 | 0 | 0 | 4 | 0 |
| Morgana | 9 | 1 | 0 | 0 | 9 | 0 |
| Nidalee | 2 | 2 | 0 | 0 | 1 | 0 |
| Ornn | 22 | 4 | 1 | 2 | 22 | 0 |
| Rakan | 3 | 3 | 2 | 4 | 4 | 1 |
| Rammus | 10 | 4 | 0 | 3 | 10 | 0 |
| Rek'Sai | 17 | 4 | 1 | 5 | 17 | 5 |
| Rengar | 12 | 5 | 1 | 3 | 12 | 0 |
| Rubrivira | 11 | 5 | 0 | 0 | 11 | 1 |
| Rubrivirim | 7 | 2 | 0 | 5 | 7 | 2 |
| Sejuani | 6 | 3 | 0 | 2 | 6 | 1 |
| Sett | 3 | 2 | 1 | 1 | 4 | 0 |
| Shen | 7 | 3 | 4 | 4 | 7 | 0 |
| Sivir | 5 | 3 | 0 | 2 | 5 | 2 |
| Soraka | 15 | 5 | 0 | 1 | 15 | 1 |
| Taric | 12 | 4 | 0 | 2 | 12 | 0 |
| Teemo | 12 | 4 | 0 | 0 | 12 | 0 |
| Tristana | 10 | 3 | 0 | 0 | 10 | 0 |
| Varus | 16 | 6 | 2 | 3 | 16 | 1 |
| Veigar | 14 | 6 | 1 | 2 | 14 | 1 |
| Vi | 8 | 4 | 0 | 8 | 9 | 1 |
| Warwick | 4 | 3 | 2 | 1 | 3 | 2 |
| Xayah | 23 | 2 | 0 | 10 | 24 | 1 |
| Yorick | 7 | 5 | 0 | 5 | 7 | 2 |
| Yunara | 5 | 3 | 0 | 0 | 5 | 1 |
| Zyra | 9 | 5 | 0 | 5 | 9 | 2 |

No modelo ativo, **30 nomes** têm menos de dez recortes de treino e **13 nomes** não têm nenhum exemplo de validação nem teste.

Sem validação nem teste: Alune, Dragão Ancião, Draven, Gnar, Lillia, Lux, Master Yi, Morgana, Nidalee, Rubrivira, Teemo, Tristana, Yunara.

Região dos recortes do treino ativo: bench=138, board=384, manual_extra=22, unknown=120. `unknown` é região não identificada; os 22 manuais não têm esta anotação.

## Interpretação e próximo passo

Contagem não é precisão. Há classes com 1–3 exemplos, poses correlacionadas e grupos sem avaliação. No quadro investigado, uma pequena alteração de recorte mudou LeBlanc de 0,808 para 0,359, Akali de 0,604 para 0,080 e Gnar para Lillia; esses escores são confiança interna não calibrada. O classificador realmente confunde aparências diferentes, e não apenas deixa nomes aguardando confirmação temporal.

O passo seguinte é revisar uma amostra cega dos recortes por grupo de origem, separar identidade confirmada de incerta e reservar grupos inteiros para avaliação. A definição de novo conjunto, critério de aceitação e treino fica para aprovação do usuário. Nesta auditoria não se iniciou treino, mudou limiar ou promoveu pesos.

Trabalho diagnóstico pendente preservado: `apps/hud_mapper/hm/board_hub_live.py`, `apps/hud_mapper/hm/runtime_session.py`, `apps/hud_mapper/hm/visual_tracks.py`, `apps/hud_mapper/tests/test_visual_tracks.py`, `training/replay_hud_diagnostics.py` e `ui/tauri-design/connected.js`.
