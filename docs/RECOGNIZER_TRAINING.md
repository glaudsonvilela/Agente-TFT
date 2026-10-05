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
