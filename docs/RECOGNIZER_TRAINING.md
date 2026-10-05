# Treinamento do reconhecedor — missão em andamento

## Checkpoint de 05/10/2026

O objetivo é reconhecer unidades reais em VODs diferentes dos usados para
treino, medir confusões por identidade e reaproveitar os dados entre patches.
Não há ativação deste modelo no instalador neste checkpoint.

Implementação nativa Rust em `tools/unit-features-lab`:

- `vod-collector`: amostra VODs, detecta barras verdes, salva recortes,
  embeddings DINO INT8, quadros de contexto e proveniência. Previsões nunca
  viram rótulos automaticamente.
- `train-classifier`: treina classificadores softmax supervisionados com
  pesos balanceados por classe, sobre cores, DINO e DINO + cores.
- `evaluate-vod-head`: reutiliza embeddings selados por hash para avaliar
  novos classificadores e produzir uma fila de divergências para revisão.
- `contact-sheet`: monta páginas de recortes para inspeção visual.
- `fetch-vod-segments.mjs`: aquisição de segmentos públicos autorizados;
  Node é usado apenas para download, não para visão ou treinamento.

`live.rs` contém um observador experimental anterior. Não existe perfil
ativo nem pacote de modelos instalado por este trabalho. Alterações Python
anteriores da integração das dicas continuam pendentes na árvore de trabalho.

## Primeiro treinamento real de uma camada de identificação

Usa as anotações existentes, verificando hashes, catálogo e separação por
fonte/sessão/partida. DINO permanece congelado: os pesos novos são os da
camada classificadora. Não confundir isso com retreino do backbone.

| Entrada do classificador | Acertos nos 29 recortes nomeados antigos |
|---|---:|
| Histogramas espaciais HSV | 9 |
| Vetores DINO INT8 | 22 |
| DINO + HSV com pesos iguais | 14 |

A comparação anterior por vizinho mais próximo obteve 20/29 com DINO.
Esses poucos exemplos já foram reutilizados no desenvolvimento; não demonstram
precisão em uma partida nova. A validação antiga tem somente três unidades
nomeadas. Alguns IDs de treino têm apenas um exemplo. Softmax não foi calibrado
e não é autorização para declarar identidade verificada.

Relatório reproduzível: `evidence/recognizer-training-20261005/initial-supervised-report.json`.
Modelos e imagens ficam no SSD privado. O checkpoint JSON registra diretórios,
fontes e contagens alcançadas, sem URLs temporárias dos segmentos.

## Fontes novas e separação

- Avaliação: <https://www.twitch.tv/videos/2883698368>, k3soju, primeiras
  seis horas contínuas, grade de 10 segundos (2.160 amostras planejadas).
- Ampliação do treino: <https://www.twitch.tv/videos/2891050468>, Dishsoap,
  13.740 segundos, grade de 20 segundos (687 amostras planejadas).
  Essa fonte já pertencia exclusivamente ao treino.

O usuário declarou autorização dos criadores para treinamento. As mídias
continuam privadas. O título/data do VOD não comprovam o patch exato.
O catálogo visual está vinculado ao Set 18; vinculação exata de patch exige
evidência adicional quando não houver indicação visível.

A coleta extensa usa decodificação de keyframes para reduzir o custo de
decodificar vídeos longos. Os tempos são a grade nominal do filtro FFmpeg,
não PTS exatos dos quadros originais; podem ter deslocamento dentro do GOP.
Uma coleta separada de 180 quadros a 1 Hz usa decodificação completa.
Nenhuma dessas medições demonstra FPS da captura/preview no Windows.

## Atualizações sem refazer tudo

1. Manter captura, geometria, pré-processamento e encoder versionados por
   contrato. Revalidar a geometria se a interface do jogo mudar.
2. Vincular cada exemplo a fonte, instante, pixels, revisão, conjunto e
   identidade oficial. Revisões incertas ficam fora do treino.
3. Armazenar embeddings uma vez por hash de pixels + encoder + pré-processamento.
   Treinar a camada pequena novamente sem reprocessar o vídeo inteiro.
4. Manter uma galeria por conjunto/aparência. Mudanças numéricas de balanceamento
   atualizam regras/atributos e exigem regressão, sem obrigar novo treinamento
   visual. Aparências novas exigem novos exemplos.
5. Priorizar exemplos divergentes, desconhecidos, ocluídos e classes com pouca
   cobertura. Avaliar sempre em fonte separada e conservar testes anteriores.
6. Publicar um modelo apenas quando a cobertura, erros por classe, rejeição de
   não unidades e latência estiverem medidas. Não promover candidatos apenas
   porque produziram mais respostas.

Essa abordagem de classificador treinado sobre características congeladas é
compatível com a avaliação linear descrita no
[repositório DINOv2](https://github.com/facebookresearch/dinov2/blob/main/dinov2/eval/linear.py).
Aqui usamos uma implementação própria pequena em Rust, com protocolo e dados
TFT; não reproduzimos os resultados publicados do DINOv2.

## Segundo checkpoint: coleta concluída e desafio maior

As duas coletas terminaram:

| Fonte | Duração amostrada | Quadros | Recortes propostos |
|---|---:|---:|---:|
| k3soju, avaliação | 6 h | 2.160 | 9.554 |
| Dishsoap, treino | 3 h 49 min | 687 | 3.345 |

São propostas do detector de barras, não unidades todas corretamente localizadas.
A revisão adicionou 123 unidades e 3 negativos de 22 quadros da fonte de treino.
O conjunto passa a 316 recortes nomeados de treino e 53 dos 74 IDs do catálogo.
21 IDs ainda não têm exemplo nomeado. Formas sazonais contam separadamente.

No VOD independente, uma grade de revisão a cada dez minutos produziu 137
propostas: 107 recortes únicos revisáveis, 29 ambíguos excluídos e uma repetição.
Dos 107, 98 são unidades e 9 são recortes sem unidade. São rótulos revisados
pelo assistente, sem confirmação humana independente. A exclusão dos ambíguos
favorece exemplos legíveis, portanto não é acurácia de todos os 9.554 recortes.

| Método | Acertos nos 107 revisados |
|---|---:|
| Galeria DINO original, vizinho mais próximo | 25 |
| Classificador inicial | 33 |
| Classificador com os 123 novos exemplos | 38 |
| Classificador ampliado com variações sintéticas | 37 |

As variações sintéticas são espelhamento, brilho 0,75/1,25 e máscara aproximada
de fundo, aplicadas exclusivamente ao treino. Não representam novos vídeos nem
uma segmentação confirmada. Essa tentativa não resolveu a diferença entre fontes.

**O modelo permanece inadequado para ativação nas dicas.** A avaliação maior
expôs erros que o conjunto antigo pequeno escondia. Há ganhos em Rammus e
Rengar e regressões em Camille/Shen. O custo da camada classificadora é cerca
de 0,04 ms por recorte nesta CPU, excluindo DINO, captura e localização.
O custo mediano do caminho completo do coletor foi ~276 ms/quadro; inclui PNG,
não mede a janela ao vivo do Windows. Não confundir esses dois tempos.

O treino agora aceita cache de embeddings por encoder, pré-processamento,
tamanho e **lote ordenado**: quantização dinâmica pode depender dos demais
exemplos no lote. Isso evita reutilização incorreta por hash de pixel isolado.

Próxima investigação: associação entre recorte e unidade, diferença de arena,
cobertura e confiabilidade dos rótulos. `mine-tooltip-labels` procura nomes
explícitos nos painéis do próprio jogo e sugere recortes com contorno ciano
para revisão; essa associação não vira rótulo automaticamente.

Os contratos nativos do primeiro checkpoint passaram em Linux e Windows no CI.
Dois jobs gerais de Windows expuseram uma falha anterior de checksum das tabelas
econômicas causada por conversão de fim de linha. `.gitattributes` fixa LF para
JSON de configuração; a verificação de hash continua exigida.

## Terceira fonte e reconciliação dos rótulos

A terceira coleta (`twitch:2891052706`, k3soju) terminou: 3 h 37 min,
651 quadros, 2.615 recortes propostos. Não são 2.615 exemplos rotulados.
Uma revisão por grade temporal adicionou 52 unidades e 2 negativos de 13
quadros; 18 propostas ambíguas da grade ficaram excluídas. O conjunto atualizado
está em `configs/training/unit-gallery-arena-20261005.json`: 366 unidades de
treino, 57 dos 74 IDs e 17 IDs ainda sem exemplo. A fonte inteira fica em treino;
o VOD de seis horas continua separado.

Uma nova revisão dos 348 recortes nomeados anteriores encontrou 23 rótulos
incorretos e excluiu 2 casos ambíguos. Exemplos: Amumu/Cinderling, Camille/Kog'Maw
e Leona/Shen. Isso é um defeito do conjunto de dados, não uma melhoria do encoder.
Os oito exemplos antigos de Ahri estavam corretos; Yunara com esferas douradas
aparece na terceira fonte. O histórico de cada correção inclui imagem, caixa,
chave, hash e rótulos anterior/novo em `label-corrections.json`.

Usamos os [renders nomeados do Set 18](https://modelviewer.lol/extras) como
referência adicional de aparência, confrontados com os quadros e painéis do
jogo. Eles não entram como imagens de treino. A documentação do visualizador
descreve [diferenças entre os assets antigos e os modelos do Set 18](https://docs.modelviewer.lol/tft-unreal-extraction).
Referências visuais ajudam a revisar; não substituem validação independente.

Também corrigimos três rótulos do desafio: duas imagens de Taric anteriormente
marcadas Ezreal e uma LeBlanc marcada Fiddlesticks. A avaliação reconciliada
continua com 107 recortes. Todos os modelos comparados foram reavaliados nela:

| Modelo | Acertos / 107 |
|---|---:|
| Galeria original | 25 |
| Classificador inicial | 33 |
| Classificador ampliado anterior | 38 |
| Apenas correções de rótulos | 41 |
| Correções + terceira fonte | 46 |

No teste antigo de 29 unidades, o último modelo acertou 21; o ampliado anterior
acertava 22. Não há melhora uniforme. A validação usada para selecionar épocas
ainda tem somente três unidades e precisa ser ampliada. O desafio de seis horas
já foi consultado repetidamente: é evidência de desenvolvimento, não um teste
final intocado. Todos os rótulos continuam sendo revisão do assistente, sem
confirmação humana independente. Nenhum modelo foi aprovado para uso nas dicas.

Para reduzir erros de associação, as folhas de revisão agora exibem o índice
global de cada recorte. Novos rótulos trazem o hash dos pixels do recorte;
o carregador Rust recusa vínculos incompatíveis entre identidade e recorte.
Os exemplos incertos são excluídos, nunca convertidos em negativos só porque
a identidade não pôde ser determinada.

## Validação ampliada e estudo do recorte

O vídeo `youtube:af1zvuCmr58` inteiro passou de treino para validação: agora são
32 unidades de validação, em vez de 3, e 337 unidades de treino. Essa fonte já
participou de treinos anteriores, portanto não é um novo teste final. Os dois
classificadores deste estudo foram treinados novamente, com o encoder DINO fixo.
Os 107 exemplos revisados do VOD de seis horas continuam fora do treino e da
seleção de época; foram incorporados ao manifesto de avaliação para medir
transformações do recorte sem reutilizar embeddings incompatíveis.

| Entrada do encoder | Validação / 32 | Desafio de desenvolvimento / 107 |
|---|---:|---:|
| Recorte original 128 × 144 | 11 | 40 |
| Centro 88 × 120, redimensionado | 15 | 55 |

O centro remove a faixa superior dos itens e parte das laterais; pode também
cortar armas e unidades grandes. Não é segmentação do personagem. A comparação
40 → 55 usa a mesma divisão ampliada; o resultado anterior de 46 usava mais
exemplos de treino e outra validação. Há melhora neste estudo, mas a precisão
continua insuficiente. Os relatórios completos e hashes ficam em
`docs/evidence/recognizer-training-20261005/feature-study-*.json`.
O artefato identifica a transformação; a avaliação de VOD recusa usar a cabeça
centralizada com o cache antigo de recortes completos. Nenhuma foi ativada.

Uma quarta fonte, `youtube:UcztPIRD1m0` (Lemuria TFT), foi coletada em 1080p:
330 quadros amostrados em 660 segundos e 66 quadros completos para revisão.
É um vídeo anterior ao patch atual, com unidades de custo cinco; os nomes dos
capítulos são pistas de revisão, não rótulos automáticos. Aparências e variantes
precisam ser reconciliadas antes de adicionar exemplos ao treino.

## Barras com divisões densas e unidades de custo cinco

Alune de três estrelas não chegava ao classificador em um quadro da quarta
fonte: as divisões escuras da barra reduziam a fração de pixels verdes abaixo
do limite. O detector Rust recebeu a opção experimental `allow_dense_ticks`,
desativada por padrão. Ela exige muitas divisões internas escuras, largura
mínima e as mesmas bordas externas; não identifica o campeão nem mede seu HP.

`scan-bars` compara as duas políticas diretamente nos quadros. Em 872 quadros
de quatro fontes, houve 22 caixas novas ou alteradas: 19 na quarta fonte,
2 na fonte de seis horas e 1 no primeiro VOD de treino. Seis caixas anteriores
foram substituídas, portanto o acréscimo líquido foi de 16 propostas. Os 22
recortes alterados mostravam unidades visíveis na revisão do assistente; isso
não mede recall nem comprova precisão global. Três regressões sintéticas
verificam barras verdes/vermelhas, rejeição de lacunas claras e ausência de
borda, além de preservar a barra sólida. Perfis existentes mantêm a opção
desligada. O coletor agora registra hash do perfil e a opção utilizada.

A coleta experimental completa da quarta fonte produziu 842 propostas em
330 quadros. Uma revisão de 83 recortes selecionados adicionou 60 unidades e
7 negativos de 12 quadros; 16 casos ficaram excluídos. Não se usaram previsões
do modelo como rótulos. Alune, Draven, Kennen e Dragão Ancião foram vinculados
às aparências nomeadas do catálogo. O patch exato do vídeo continua desconhecido;
essas imagens não fornecem atributos de combate do patch atual.

O manifesto `unit-gallery-five-cost-20261005.json` tem 397 unidades de treino,
60 dos 74 IDs representados e a mesma validação de 32 unidades. Com o recorte
centralizado, o novo classificador acertou 16/32 na validação e 62/107 no desafio
revisado (antes: 15/32 e 55/107). Os 107 incluem 98 unidades e 9 não unidades.
Os três exemplos de Kennen desse desafio passaram a ser reconhecidos, mas houve
regressões em outros casos; uma Diana passou a ser confundida com Alune.

O treino ajustou apenas a cabeça de classificação, com DINO INT8 congelado.
Restam 14 IDs sem treino, além de erros e exemplos escassos nas classes cobertas.
Cobertura de catálogo não significa precisão suficiente. Os pesos ficam no SSD,
com hash e métricas no Git; continuam sem aprovação para as dicas do Windows.

## Expansão de Morgana e auditoria reproduzível

A quinta fonte de treino, `youtube:nxSUNW1yZqI` (KH-Teamfight Tactics TFT,
publicada em 2026-09-08), forneceu 711 propostas em 69 quadros de 23 minutos.
Uma grade temporal de dois minutos foi revisada: 138 propostas, 99 identidades
visualmente nomeadas, 39 casos ambíguos excluídos. Limitamos repetições a seis
exemplos por classe estabelecida e oito de Morgana, distribuídos ao longo do
vídeo. Entraram 72 exemplos de 12 quadros; outros 27 ficaram fora por repetição.
O vídeo inteiro permanece em treino. O patch exato não foi confirmado.

O conjunto resultante tem 469 unidades de treino, 61/74 IDs representados e
13 IDs ausentes. A nova cabeça centralizada obteve 17/32 na validação e 59/107
no desafio de desenvolvimento, contra 16/32 e 62/107 anteriormente. Isso expõe
uma regressão entre fontes; os dois artefatos foram preservados e nenhum foi
promovido ao software. O aumento de cobertura não comprova melhora geral.

`audit-dataset` revalida os hashes, vínculos de recorte e isolamento das fontes
antes de listar cobertura por classe e divisão. A auditoria atual encontrou
18 classes com exemplos de treino provenientes de uma única fonte. Esse número
orienta a próxima coleta; contagens de recortes não representam partidas
independentes. Execute com o catálogo correspondente:

```sh
cargo run --release --manifest-path tools/unit-features-lab/Cargo.toml \
  --bin audit-dataset -- ANNOTATIONS_JSON IMAGE_ROOT REFERENCE_DIRECTORY NEW_REPORT_JSON
```

A transformação `center_88x120_v1` passou para `crop_transform.rs`, reutilizável
pelas ferramentas nativas. Um novo treino com os mesmos dados e configuração
produziu exatamente o mesmo artefato anterior, SHA-256
`3d379ad94cebd588c23117e16910b9d5c250a42753c42f5c79717e99c901437f`.
Dois testes adicionais verificam retirada da faixa superior/laterais sem mudar
o original e rejeição de recortes corrompidos/versões desconhecidas. Isso ainda
não equivale a integração validada no fluxo ao vivo do Windows.

Também coletamos a prévia de Lux `youtube:qkG10NeqM3A`: 15 quadros e 69 propostas.
Por ser uma prévia anterior ao PBE e não confirmar a variante na interface,
ela não entrou no treino. A semelhança de cores não basta para vincular as
nove formas sazonais de Lux ao ID correto.

## Busca dirigida e correção de invocações sazonais

Uma fila de revisão procurou classes com até três exemplos nos VODs de treino,
limitando fonte e proximidade temporal. As sugestões de identidade foram ocultadas
nas folhas de revisão. Das 75 propostas, 58 puderam ser nomeadas ou classificadas
como cenário; quatro já estavam anotadas. Entraram 52 unidades e 2 negativos,
incluindo as primeiras aparências de Nidalee e Tristana. Os demais casos ficaram
sem rótulo; a escolha do modelo para montar a fila não é verdade de referência.

A revisão seguinte encontrou nove erros introduzidos nas expansões recentes:
plantas com flor amarela haviam sido chamadas de Rammus. Os renders nomeados de
Rammus mostram outra aparência, e a [descrição oficial da Riot](https://teamfighttactics.leagueoflegends.com/en-sg/news/game-updates/enchanted-wilds-overview/)
confirma invocações de Elderwood e a montaria Sprykin. Removemos esses nove
exemplos do treino de campeões; não os transformamos automaticamente em exemplos
de uma invocação específica. Os três exemplos de Rammus no desafio estavam
corretos. Validação e teste permaneceram inalterados.

`seasonal-summon-quarantine.json` registra cada retirada. `excluded_entities`
preserva o recorte para investigação; o carregador Rust recusa sua reintrodução
como campeão, inclusive se a chave da entidade mudar. O inventário sazonal
`configs/vision/seasons/TFTSet18/entity-scope-v1.json` separa campeões, invocações
e estados montados, sem alterar a geometria fixa. Esse inventário ainda não é
um detector implementado dessas entidades.

O conjunto corrigido contém 512 unidades de treino, 63/74 IDs, 11 IDs ausentes
e 16 classes com apenas uma fonte de treino. O novo modelo acertou 18/32 na
validação e 62/107 no desafio revisado. Esses números continuam insuficientes
para promoção; os modelos anteriores às correções ficam como histórico.
Onze testes da biblioteca Rust passaram, incluindo a proteção de quarentena.

Uma fonte adicional de Tristana (`youtube:T4lJ2S2iH_o`, Minjo TFT) foi baixada.
A primeira coleta terminou com código 143, sem causa confirmada; os logs parciais
foram preservados. Com o processo verificado como encerrado, a retomada em outro
diretório completou 47 quadros e 147 propostas entre 100 e 570 segundos.
O vídeo mostra um caso importante de campeão montado. Ele permanece sem rótulos
e fora do treino; a próxima revisão deve ampliar a avaliação entre fontes.

## Primeira avaliação na nova partida de Tristana

Uma grade de 30 segundos da coleta retomada produziu 46 propostas para revisão.
Retivemos 35 recortes legíveis e excluímos 11 ambíguos. O manifesto separado
`unit-gallery-tristana-evaluation-20261005.json` reserva o vídeo inteiro para
avaliação. As identidades foram revisadas antes da execução do classificador;
continuam sendo rótulos do assistente, sem confirmação humana independente.

O comando Rust `evaluate-classifier --spec CONFIG_JSON` usa o encoder e a cabeça
congelados, valida seus hashes, o vínculo com o manifesto de treino e os pixels
dos quadros. Ele rejeita partidas/fontes/pixels compartilhados com o treino.
O carregador específico de avaliação aceita apenas a divisão `test`; a API
de treino continua exigindo as três divisões não vazias. Nenhum peso foi ajustado.

Com o modelo corrigido de 512 unidades de treino, o resultado foi:

| Condição revisada | Acertos | Exemplos |
|---|---:|---:|
| Aparência comum | 22 | 32 |
| Tristana montada no companheiro Sprykin | 0 | 3 |
| Total | 22 | 35 |

Os quatro recortes comuns de Tristana foram reconhecidos. A montaria é uma
lacuna distinta de aparência. O vídeo também contém ampliação editorial:
alguns quadros de 1080p não mostram a interface inteira e têm outra escala.
Só marcamos o enquadramento quando o quadro completo foi verificado; os demais
ficam `not_reviewed`. Há apenas dois recortes na categoria de zoom verificada,
insuficientes para concluir a precisão nessa condição.

Esse resultado mede somente as propostas legíveis revisadas, sem contar
campeões que o localizador perdeu. A fonte é anterior ao lançamento e o patch
exato não está confirmado. Depois dessa inspeção, ela passa a ser evidência de
desenvolvimento e não pode ser anunciada como teste final intocado. Os próximos
exemplos montados devem vir de outra fonte. O modelo continua sem promoção.

Também comparamos o mesmo artefato com lotes de 1 e 4 recortes: quatro das 35
previsões mudaram, com 21 e 22 acertos, respectivamente. As execuções isoladas
levaram cerca de 1,62 s cada para os 35 recortes, sem captura, carregamento ou
exibição. Não é uma medida de FPS do HUD. Essa dependência do lote no encoder
INT8 exige uma política explícita e idêntica no treino e na inferência; o próximo
experimento usará um recorte por lote para retirar a influência dos vizinhos.

## Política explícita de um recorte por chamada INT8

O treinador Rust agora registra `embedding_batch_size` no artefato e no relatório.
O avaliador usa esse valor por padrão; substituições experimentais ficam explícitas
no relatório. Artefatos históricos sem o campo mantêm a interpretação original de
lote 4. Valores inválidos são rejeitados. Quinze testes passaram.

Retreinamos a mesma cabeça linear e o mesmo conjunto corrigido, sem acrescentar
rótulos, com lote 1. O encoder permanece congelado. O resultado foi 17/32 na
validação, 62/107 no desafio de desenvolvimento e 20/35 na fonte Tristana.
A política foi escolhida para eliminar a influência de outros recortes; esses
resultados não demonstram melhora de precisão.

Executamos novamente as 35 imagens de Tristana com quadros e entidades em ordem
inversa. Com o mesmo artefato, as 35 previsões e suas pontuações máximas foram
idênticas (diferença máxima zero). `batch1-order-invariance.json` registra os hashes
comparados. Isso valida a invariância nessa amostra; não é uma avaliação de captura,
FPS ou execução no Windows. O artefato continua sem autorização para promoção.

Também concluímos a coleta de `youtube:T0KVjZtR3GY` (Void TFT, Elise): 66 quadros,
237 propostas em 660 segundos e 89 propostas em uma grade de revisão de 30 segundos.
Nenhuma proposta dessa fonte foi ainda adicionada como rótulo. Vídeo, recortes e
pesos ficam no SSD; os relatórios e manifestos são versionados no Git.

## Elise e revisão de identidades antigas

A revisão de 89 propostas do vídeo de Elise acrescentou 44 unidades nomeadas e
sete recortes sem unidade; 38 propostas ambíguas ou redundantes ficaram de fora.
Oito exemplos são de Elise em forma humana. Sua forma de aranha permanece sem
cobertura revisada. Os renders nomeados permitiram distinguir Elise de Morgana;
nenhuma sugestão do classificador foi promovida automaticamente a rótulo.

A versão intermediária passou a 556 unidades de treino e 64/74 IDs. Os dez IDs
faltantes são variantes de Lux. O artefato com lote 1 acertou 19/32 na validação,
60/107 no desafio de desenvolvimento e 20/35 na partida de Tristana. A expansão
não demonstra melhora generalizada: os resultados variam entre as amostras.
`elise-expanded-report.json` preserva essa execução, sem promoção ao aplicativo.

Também revisamos 63 exemplos de quatro classes com baixo acerto no próprio treino.
A inspeção visual encontrou 11 identidades incorretas: oito Alune marcadas como
Diana, uma Caitlyn marcada como Diana, um Brambleback marcado como Diana e um
Kog'Maw marcado como Soraka. Seis outros recortes ficaram em quarentena porque
oclusão ou aparência conflitante não permitem confirmar a identidade. A revisão
atinge somente treino; validação e testes não foram alterados. O novo manifesto
`unit-gallery-label-reconciled-20261005.json` e o registro
`low-fit-label-corrections.json` conservam as mudanças e seus motivos.

Uma segunda partida com Sprykin, do canal Padado (`youtube:bJF34u5fkGw`), foi
baixada para procurar aparências montadas fora da partida reservada à avaliação.
A coleta nativa está em execução. Nenhum recorte dessa nova fonte entrou no treino.

Após a reconciliação, o novo treino terminou com 550 unidades nomeadas, 64 IDs
cobertos e 15 classes sustentadas por uma única fonte de treino. O acerto no próprio
treino foi 511/550; esse número não comprova generalização. Na validação foram
19/32, no desafio 62/107. A avaliação de Tristana está registrada integralmente
em `tristana-label-reconciled-evaluation.json`. Os pesos permanecem privados no
SSD e não foram ativados no Windows.

## Segunda revisão e exemplos montados de outra partida

A conferência seguinte examinou os 39 erros restantes no treino e cruzou os 14
exemplos rotulados como Morgana. Encontrou oito outras identidades incorretas e
um erro desta expansão: seis exemplos novos do vídeo de Elise eram Camille,
não Morgana. A referência em tamanho completo mostra suas pernas em lâmina e a
coroa; Morgana usa vestido longo e capuz. Corrigimos esses seis exemplos e os oito
outros casos, e colocamos 11 recortes ambíguos em quarentena. Os registros anteriores
permanecem como histórico, não como a versão ativa dos rótulos.

`unit-gallery-identity-reconciled-20261005.json` contém 539 unidades nomeadas de
treino. Com lote 1 e encoder congelado, a cabeça obteve 19/32 na validação, 62/107
no desafio e 22/35 na partida de Tristana. A anotação continua sendo revisão do
assistente, sem confirmação humana independente; a inspeção por erro de treino
ajuda a localizar problemas, mas não certifica os demais rótulos.

A coleta Padado terminou: 218 quadros, 1.166 propostas e 109 imagens completas de
revisão, em 2.180 segundos de vídeo. Selecionamos seis instantes previamente à
avaliação; quatro tinham propostas, totalizando 43 recortes. Trinta identidades
legíveis foram adicionadas, incluindo três Tristana montadas e dois Rammus montados.
Treze propostas ficaram de fora por ambiguidade ou redundância. Um dos recortes
vem da barra inferior da mesma montaria e foi registrado como duplicata, sem
contar outro campeão. A deduplicação dessas barras ainda não está implementada
no aplicativo.

O manifesto `unit-gallery-sprykin-expanded-20261005.json` contém essa expansão.
Todos os quadros de validação e teste foram comparados e permanecem idênticos aos
da versão anterior. O vídeo Minjo usado na avaliação não entra no treino.

O treino com os 30 exemplos adicionais terminou com 569 unidades nomeadas e 13
classes presentes em apenas uma fonte de treino. Foram 17/32 na validação,
64/107 no desafio e 22/35 na avaliação Minjo. Os três recortes montados dessa
avaliação continuam errados (0/3); portanto, não declaramos a lacuna resolvida.
A validação piorou de 19 para 17 acertos e impede tratar a expansão como melhora
uniforme. `sprykin-expanded-report.json` e
`tristana-sprykin-expanded-evaluation.json` registram todos os resultados.

Há uma diferença visível que precisa de controle no próximo experimento: a
interface do quadro Padado em 2.000 s mostra cinco Sprykin; a interface Minjo em
300 s mostra sete. Os recortes montados de Minjo também têm galhadas douradas e
outra orientação, enquanto os exemplos de Padado mostram a frente da montaria
com galhadas cinza/azul. Isso documenta condições distintas, sem atribuir toda a
falha a uma causa única. Precisamos de outra fonte com a aparência correspondente
ou de uma representação que preserve melhor o próprio cavaleiro. Nenhum artefato
foi promovido; aumentar o número de recortes, sozinho, não comprovou transferência.

## Comparação de regiões com a mesma base

Comparados três enquadramentos nativos, mantendo os mesmos 569 exemplos, as
mesmas divisões, encoder congelado e lote 1. A região `upper_88x80_v1` usa x=20,
y=24, largura=88 e altura=80 do recorte original 128×144. O treinamento e o
avaliador usam a mesma implementação versionada; o gerador de folhas de revisão
também pode mostrar a transformação efetiva. Nenhuma imagem original é alterada.

| Região | Validação | Desafio de desenvolvimento | Fonte Tristana |
|---|---:|---:|---:|
| Inteira (`raw`) | 14/32 | Relatório integral preservado | Não executado |
| Central 88×120 | 17/32 | 64/107 | 22/35 |
| Superior 88×80 | 18/32 | 63/107 | 27/35 |

A seleção seguiu macro recall de validação, com entropia cruzada como desempate,
registrada em `region-experiment-protocol.json`. A fonte Tristana foi avaliada
após selecionar a região superior. Os três casos montados continuam errados;
os 27 acertos estão entre os 32 recortes comuns. Uma única imagem a mais na
validação pequena não comprova superioridade geral. A inferência dos 35 recortes
levou aproximadamente 1,61 s nesta execução, sem captura ou exibição do Windows.
Os 16 testes da biblioteca e do avaliador passaram. O artefato continua sem promoção.

A busca por sete Sprykin encontrou outra partida KH (`youtube:Jmi5fbZiFGU`), e
uma partida shurkou com Lux (`youtube:CQhg2_6tzcM`) foi baixada. Ambas estão em
coleta nativa, sem rótulos automáticos. O título do vídeo não confirma identidade.

O auxiliar OCR de revisão também recebeu uma correção: a palavra genérica Lux
não pode identificar automaticamente `DA_Lux18_Base`. Agora conserva todos os IDs
da família e exige revisão da variante; nomes compostos são comparados completos.
Um teste cobre Lux genérica, variante explícita, nome composto, texto extra e baixa
confiança. A associação entre painel e recorte continua exigindo revisão visual.

A coleta KH com sete Sprykin terminou com 62 quadros e 479 propostas. O quadro
1.120 s confirma visualmente sete Sprykin e Rammus na montaria com galhadas douradas.
Foram preparadas 53 propostas para revisão; ainda não são rótulos de treino.

## Fonte com sete Sprykin e retomada de Lux

A revisão KH acrescentou 41 identidades de 53 propostas, incluindo seis casos
montados de três campeões. O quadro de 960 s confirma sete Sprykin e Tristana na
montaria dourada. A base resultante tem 610 unidades nomeadas e 64/74 IDs.
Treino e avaliação usam a região superior e lote 1, sem alterar os quadros de teste.
O resultado foi 19/32 na validação, 66/107 no desafio e 31/35 na fonte Minjo:
30/32 comuns e 1/3 montados. O artefato permanece sem promoção; os dois erros de
montaria e os dois recortes com zoom continuam abertos.

A coleta Lux sofreu dois encerramentos com código 143, sem causa confirmada.
Preservamos os arquivos originais e os prefixos de registros completos; a última
linha truncada não foi tratada como observação válida. As retomadas começaram em
1.520 s e 1.780 s, após confirmação de término do processo anterior. O segmento
final completou 17 quadros e 150 propostas. Os prefixos anteriores contêm 76 e 13
registros completos; seus arquivos de embeddings não são declarados íntegros.
O auxiliar OCR não encontrou painéis válidos no segmento final. Nenhuma identidade
Lux foi adicionada com base somente no título, cor ou nome genérico.

## Recuperação verificável de coletas interrompidas

O comando Rust `reconcile-collection --spec RECONCILIATION_JSON` reúne segmentos
concluídos e prefixos interrompidos explicitamente registrados. Verifica a grade
completa de tempos, rejeita sobreposições/lacunas e confere pixels dos quadros,
recortes salvos e sua associação com a região original. Uma linha JSON truncada
só pode ser ignorada no final de uma entrada marcada como interrompida; corrupção
anterior ou em uma coleta concluída é erro. Os arquivos originais são preservados.
Dois testes exercitam essas falhas de recuperação e de cobertura temporal.

A execução real recuperou os 106 quadros de revisão e 738 recortes da fonte Lux,
sem lacunas na grade de 20 segundos. O índice usa `review_frames_complete`;
não reconstrói nem declara válidos os embeddings interrompidos. O auxiliar OCR
aceita esse índice verificando seu hash e os pixels de cada quadro. A revisão OCR
dos 106 quadros não encontrou painel de unidade elegível. Isso não é prova de que
não houve painel entre amostras. Iniciamos uma coleta de 1 Hz em 1.240–1.280 s,
quando a característica Avatar aparece, para procurar a aquisição de Lux e sua
forma sem depender somente da cor ou do título do vídeo.

## Lux Elderwood: vínculo pela loja e pela sequência de compra

A revisão dos 40 quadros da coleta de 1 Hz encontrou, em **1.253 s**, a carta
“Lux” com “Elderwood”, “Avatar” e o texto “Elderwood Bonus”. Os quadros seguintes
mostram a compra, a unidade no banco e sua colocação no tabuleiro. Esse vínculo
visual permite rotular cinco recortes espaçados em 1.320, 1.440, 1.560, 1.780 e
1.900 s como `DA_18_Lux_Elderwood`. Os hashes e a base da revisão estão em
`lux-elderwood-training-labels.json`. O OCR de painel lateral não encontrou esses
textos, pois a informação estava na loja e no tooltip de habilidade, fora de sua
região fixa. A revisão é do assistente, sem validação humana independente.

O manifesto `unit-gallery-lux-elderwood-expanded-20261005.json` contém **615
exemplos nomeados de treino e 65/74 IDs**. A nova cabeça DINO INT8 com região
`upper_88x80_v1` e lote 1 obteve **19/32 na validação, 66/107 no desafio de
desenvolvimento e 31/35 na fonte Minjo**. Os cinco exemplos Lux vêm de uma única
partida; não demonstram generalização de Lux. Nove variantes ainda não têm treino.
Reservamos a fonte `youtube:ezSEOwI7uOM` exclusivamente para avaliação antes de
revisar suas imagens. A cabeça está congelada para essa avaliação e permanece
sem aprovação para o runtime Windows.

### Primeira avaliação na segunda partida de Lux

A fonte KH foi coletada por completo (72 quadros, 766 propostas). Antes de
consultar previsões, a revisão fixou 35 rótulos de 13 IDs, incluindo três Lux;
23 propostas ambíguas, redundantes ou de invocações foram excluídas. Resultado
congelado: **21/35**, com **0/3 Lux Elderwood**. A arena, iluminação, pose e itens
são diferentes do treino. Essa fonte passa a ser evidência de desenvolvimento,
pois suas falhas já orientam a investigação. Os três recortes Lux pertencem à
mesma partida e não são três testes independentes de generalização.

A montagem de comparação mostrou que `upper_88x80_v1`, que começa em y=24,
corta a parte superior da cabeça dos exemplos sem a faixa de itens. A alternativa
`top_88x104_v1` preserva y=0..104 e mantém a mesma largura central. Também mantém
os itens quando presentes, portanto não é uma máscara semântica. O protocolo
`high-head-region-protocol.json` fixa os dados e a seleção pela macro-revocação
na validação, seguida da entropia cruzada; empate mantém o recorte anterior.
Quatro testes do módulo de recorte passaram. Nenhuma mudança foi ativada no HUD.

A alternativa que preserva a cabeça foi **rejeitada pela validação**: 18/32 e
macro-revocação 0,553, contra 19/32 e 0,598 do recorte anterior. Após a seleção,
a avaliação KH passou de 21/35 para 24/35, mas Minjo caiu de 31/35 para 27/35.
A mudança global de recorte não resolveu o problema com consistência. O próximo
passo é ampliar as aparições sem itens na fonte de treino e examinar a necessidade
de alinhamento condicionado à faixa de itens, mantendo a separação das partidas.

### Cobertura de Lux sem itens na própria fonte de treino

Acrescentamos três aparições da sequência de aquisição de shurkou: banco após
compra, colocação com contorno de seleção e tabuleiro sem itens. São observações
correlacionadas da mesma partida, não três partidas novas. A fonte KH permanece
exclusivamente para avaliação. A cabeça foi novamente treinada com o recorte
`upper_88x80_v1`, totalizando **618 exemplos nomeados e 65/74 IDs**.

Resultados: **19/32 validação; 66/107 desafio anterior; 31/35 Minjo; 23/35 KH**.
Lux Elderwood passou de 0/3 para **2/3** no KH sem as regressões da troca global
de recorte. O experimento sustenta ampliar cobertura por estado de aparência
(itens, pose, seleção, montaria, arena), preservando os recortes e a origem dos
rótulos. Ainda faltam nove formas Lux, precisão maior entre partidas e validação
independente. O artefato continua experimental, sem ativação no Windows.

## Comparação por exemplares revisados

Implementamos em Rust um índice de vetores com três políticas: maior similaridade
por classe, média das três maiores e média de todos os exemplares da classe.
Somente o split de treino entra no índice. O encoder e o preparo de recortes são
os mesmos do classificador; o índice pode ser reconstruído com embeddings em cache,
sem atualização de pesos. O repositório DINOv2 apresenta avaliação por vizinhos e
por camadas lineares: <https://github.com/facebookresearch/dinov2>. A agregação por
classe deste experimento é local e não reproduz o benchmark ImageNet do projeto.

O protocolo `retrieval-protocol.json` foi salvo antes da execução. Na validação,
as políticas obtiveram **14/32, 15/32 e 15/32**. A média de todos os exemplares
venceu entre elas pela macro-revocação, mas perdeu para a cabeça linear (**19/32**).
O índice contém 649 referências (618 nomeadas e 31 negativas), 66 classes contando
`__unknown__`. Não reportamos acurácia do próprio treino, pois a busca encontraria
os próprios exemplares. O índice foi rejeitado para substituir a cabeça atual.

Os 17 testes da biblioteca e dois testes de isolamento do avaliador passaram.
Após compartilhar o cálculo de métricas, a avaliação linear completa de 35 recortes
ficou idêntica, incluindo escores. O artefato de busca e seus relatórios permanecem
como experimento; nenhuma inferência foi transformada em rótulo ou ativada no HUD.

## Auxiliar Rust para localizar compras nos vídeos

O binário `mine-shop-transitions` lê uma coleta concluída, verifica os hashes dos
quadros e aplica OCR à faixa de nomes da loja. A máscara mantém os caracteres
claros, remove bordas e preços e amplia a faixa em 2×. Os nomes vêm do catálogo;
“Lux” continua com todas as variantes possíveis. Três cartas vizinhas precisam
permanecer estáveis e o intervalo entre quadros deve ser de até dois segundos.

Na sequência conhecida de 40 quadros, surgiram duas propostas: compra de Zyra
em 1.251–1.252 s e de Lux em 1.253–1.254 s. A segunda trouxe três propostas de
banco, mas duas eram Zyra já existentes, ocultas pelo tooltip anterior. Apenas a
revisão da sequência distingue a compra real. Nenhum rótulo foi criado
automaticamente e o exemplo correto de Lux já estava no treino.

Os três testes do novo auxiliar e o teste de nomes do auxiliar de tooltip
passaram. O relatório `shop-transition-review.json` registra a revisão feita
pelo assistente. Este pequeno caso conhecido não mede precisão ou revocação em
novas partidas. O próximo passo é ampliar a mineração em fontes de treino e
reduzir o custo da coleta para anotação, evitando embeddings desnecessários.
