# Coach por atributos — experimento sem habilidades

Esta etapa atende à decisão de prosseguir sem habilidades e de tratar depois
a identidade visual dos campeões. Não certifica um coach completo de TFT.

## O que o código executa

O motor `hm.strategic_coach` recebe um estado completo, confirmado, da perspectiva
do jogador e em planejamento. Examina alternativas antes de gerar texto:

| Família | Alternativas e restrições |
| --- | --- |
| Rolagem | Alvos a uma cópia de melhorar, presentes no tabuleiro; probabilidade da categoria no nível; orçamento limitado a cinco atualizações; reserva separada para a compra; limite de ouro e condição de parada. |
| Composição | Preencher uma vaga com uma peça do banco ou comparar todas as trocas individuais entre banco e tabuleiro. A peça substituída permanece no banco. |
| Posicionamento | Todos os movimentos e trocas nas 28 casas; alcance, contribuição de ataques básicos e cobertura do carregador por unidades próximas da frente. |
| Equipamentos | Item completo do inventário ou receita de dois componentes distintos; espaços disponíveis, unicidade e alternativa de conservar o item. Não equipa apenas por existir um componente. |

Uma recomendação prioritária segue para o caminho existente de voz. O histórico
mostra as quatro categorias disponíveis. São **alternativas**, reavaliadas após
cada ação, e não uma sequência para executar inteira sem nova leitura.

O catálogo sazonal fica em `configs/coaching/TFTSet18/18.3B-20260928`;
`active.json` fixa seus hashes. Geometria e lógica permanecem fora dos números
do patch. O compilador `training.build_coaching_catalog` reconstrói o catálogo
a partir do conteúdo de simulação, release selado e perfil de estrelas.

## Rede e significado do treinamento

`training.strategy_ranker_lab` gera estados sintéticos e treina uma MLP de
15 entradas, 32 unidades ocultas e uma saída: **545 parâmetros**. Há atualização
real dos pesos por gradiente. A rede aproxima um objetivo explícito de atributos,
formação, afinidade entre características e recursos.

Isso é **destilação de um avaliador projetado**, não aprendizado por vitórias,
imitação validada de desafiantes ou execução do algoritmo AlphaStar. Não usa os
10 mil testes anteriores de recursos como rótulos de estratégia. Vídeos ajudam
a formular hipóteses; narração isolada não é um estado/ação rotulado.

O split por semente é feito antes das alternativas: 80% treino, 10% validação,
10% teste. O checkpoint é escolhido somente pela validação. O teste compara
regret no objetivo, manter o estado e escolha aleatória, inclusive por família.
Concordância com o avaliador **não é taxa de acerto no TFT real**.

Os pesos exportados são JSON numérico, sem pickle. A inferência no aplicativo
usa somente a biblioteca padrão de Python. Torch permanece no treinamento.
O carregamento confere catálogo, esquema, objetivo, versão, tamanho e valores.

## Limites que continuam explícitos

- 73 entradas de campeões têm atributos utilizáveis. Kayle é rejeitada por
  ausência de AD no catálogo; nenhum número foi inventado.
- Há 27 itens vinculados e 18 receitas. Efeitos dinâmicos dos itens não entram
  neste objetivo; item desconhecido impede uma avaliação completa do estado.
- AP/mana sem execução de habilidades não mede o valor real de um carregador AP.
  O cálculo atual usa ataques básicos, resistência e HP. Isso pode alterar a
  preferência de composição/equipamento em relação ao jogo real.
- Afinidade de características não significa ativação ou simulação de todos
  os seus efeitos. Não há avaliação de aprimoramentos ou recompensas sazonais.
- A composição avaliada é uma mudança local das peças possuídas, não uma busca
  completa até a composição final. Posicionamento não prevê habilidades inimigas.
- A chance de rolagem usa aproximação de casas independentes e conjunto completo
  menos cópias próprias; não é uma chance exata com adversários desconhecidos.
  Formas de Lux compartilham a identidade do conjunto. O painel não apresenta
  essa estimativa como probabilidade observada.
- Nenhuma melhora de colocação em partidas reais está demonstrada.

## Ligação com a leitura da tela

`ReplayDecisionEngine.evaluate(..., strategy_state=...)` conecta o motor ao
formatador e à fila existente da ElevenLabs. O runtime aceita apenas o contrato
`snapshot.verified_state`, verifica época da captura e idade de até dois segundos
e rejeita incompatibilidade com uma leitura nova de ouro.

O observador B4 atual **não produz esse contrato**. Continua proibido converter
seus candidatos em identidades confirmadas. Portanto, as recomendações são
testáveis com estados conhecidos, mas estas mudanças sozinhas não liberam as
quatro dicas automaticamente sobre os pixels do Windows. Essa integração visual
foi explicitamente adiada pelo usuário nesta etapa.

Próxima etapa visual: rotular recortes reais por campeão, estrela, posição e
itens; separar treino/teste por partida; distinguir tabuleiro próprio/adversário;
calibrar rejeição de desconhecidos e rastrear mudanças temporalmente. Artes da
loja podem servir de catálogo, mas não substituem imagens dos modelos 3D. Primeiro
medir falsos reconhecimentos em sessões reservadas; depois habilitar o contrato.

## Fontes consultadas nesta etapa

- [dpei: posicionamento](https://www.youtube.com/watch?v=TXhQgEB6NS4): transcrição
  automática integral lida, 0:00–9:41; vídeo de 9:43. Critérios aproveitados como
  hipóteses: proteger o carregador, usar a frente para absorver dano e considerar
  cobertura lateral. Exemplos de sets antigos não foram tratados como atributos
  do patch atual. Nenhuma partida foi rotulada a partir desta transcrição.
- [Fundamentos do próprio criador](https://www.tftgameplan.com/fundamentals) e
  [partidas comentadas](https://www.tftgameplan.com/gameplay): índice consultado.
  Outros vídeos tentados não forneceram transcrição; não contam como revisados.
- [VODs de dpeitft](https://www.twitch.tv/dpeitft/videos): canal confirmado pelo
  link na descrição do YouTube. A gravação `2885789930` exige assinatura; somente
  os metadados foram consultados, sem contornar o bloqueio.
- [Relato original do AlphaStar](https://deepmind.google/blog/alphastar-mastering-the-real-time-strategy-game-starcraft-ii/):
  referência metodológica consultada; este experimento não reproduz sua escala,
  ambiente, treinamento com demonstrações ou liga de autojogo.

Relatórios numéricos e identidade dos pesos ficam em
`docs/evidence/strategy-coach-20261004`. Dataset integral e fontes ficam no SSD e
no diretório isolado do experimento no BigBANANA, fora do instalador.

## Resultado da execução de 04/10/2026

- BigBANANA: 10.000 estados, 202.765 alternativas de treino, 40 épocas,
  15.880 passos e quatro tensores alterados; 455,56 segundos, pico de 640,42 MiB.
- Pesos portáveis: 11.628 bytes; diferença máxima contra a inferência do treino
  de 3,89e-7. Arquivo incluído na configuração do pacote.
- O split inicial tem interação entre paridade das sementes e criação de pares:
  apenas 41 estados de teste tinham alternativas de rolagem. Por isso, uma
  auditoria adicional usou 500 sementes disjuntas, ambas as paridades e todas as
  81.757 alternativas. Incluiu 115 casos de rolagem e passou o limite declarado
  de regret médio abaixo de 0,025 em cada família, sem ajustar os pesos.
- Contrato de integração: 100 estados de teste produziram dicas e conteúdo para
  voz; p50 30,1 ms, p95 72,9 ms no computador de desenvolvimento. Não inclui
  leitura de pixels, conexão à API, reprodução de áudio ou execução no Windows.
- 36 testes de integração/regras passaram; um teste de áudio físico permaneceu
  ignorado, além de nove subtestes de rejeição de estado.

Não foi gerado um instalador novo. A configuração disponibiliza o ranker para
estados estruturados confirmados; o caminho visual continua sem identidade
confirmada e não foi promovido por estes resultados.

## Identificação visual: investigação e mudanças de 04/10/2026

O tabuleiro agora recebe quadros diretamente da captura, em fila que conserva
somente o quadro mais recente, a cada 1 segundo. Antes, dependia do término do
OCR e havia um intervalo fixo de 5 segundos para um estado estratégico que
expirava em 2 segundos. O processo Rust `AGENTE_TFT_BOARD_ONLY=1` executa apenas
geometria, sem carregar Tesseract. A VM calcula as barras a partir dos mesmos
pixels recebidos; não reutiliza as barras de uma resposta anterior do OCR.
Uma referência plana inválida é rejeitada sem encerrar esse processo.

Foi implementado um classificador ONNX de recortes das unidades, com IDs ligados
ao catálogo visual versionado, limite de propostas e rejeição de saída ambígua.
Seu carregamento é opcional, os resultados são candidatos e uma falha de
inferência desativa somente esse modelo. Nenhum candidato vira automaticamente
campeão confirmado, posição ocupada, estrela ou item equipado.

O primeiro experimento utilizou 48 recortes de unidades de oito imagens e dez
recortes negativos de HUD. Os nomes foram revisados pelo assistente, com hashes
das imagens; não constituem avaliação humana independente. Os conjuntos usam
partidas separadas: três para treino, uma para validação e uma para teste.

- 16 identidades treinadas de 74 IDs do catálogo; 600 passos, 13.753 parâmetros.
- ONNX de 56.244 bytes; p95 de 1,25 ms para inferência de um lote de 12 recortes
  neste computador, sem captura, transporte ou pré-processamento.
- Treino: 39/39 exemplos classificados corretamente, incluindo negativos.
- Validação: 1/7 correto, quatro identificações falsas aceitas.
- Teste: 2/12 corretos, seis identificações falsas aceitas e quatro abstenções.
- Resultado: **reprovado para ativação estratégica**. Os pesos permanecem no
  laboratório do SSD; não há configuração ativa desse modelo no instalador.

A consulta online incluiu reprodução de trechos de Wasianiverson no YouTube e
Dishsoap na Twitch, além de um guia com capítulos por custo. Esse guia mostra
cartas de campeões no trecho revisado, portanto não foi contabilizado como
treino de modelos 3D. As amostras deste experimento vieram das capturas locais.
O catálogo oficial também tem dez IDs de Lux com retrato idêntico: o retrato
sozinho não resolve essas variantes.

Evidências e cobertura por identidade:
`docs/evidence/visual-identity-20261004`. Rótulos reprodutíveis:
`configs/training/unit-identity-review-20261004.json`. Treinador:
`python -m training.train_unit_identity --help`.

O teste com os dois canais de OCR bloqueados respondeu ao HUB em 93,3 ms.
Isso valida a independência da análise no Linux; não mede FPS da prévia no
Windows, latência de voz, nem precisão do estado completo. Ainda faltam exemplos
variados por campeão, rejeição confiável de desconhecidos, estrelas, associação
ao hexágono, itens confirmados e perspectiva/fase. Não foi produzido novo
instalador nem habilitado o cérebro estratégico a partir desse modelo reprovado.

### Alternativa com reconhecedores separados — 2026-10-04

**Resultados históricos superados:** nove rótulos visuais foram corrigidos na
revisão descrita abaixo. As métricas semânticas desta seção e do experimento
CNN anterior não devem orientar ativação. Os arquivos originais ficam como
histórico; o treinador rejeita a anotação antiga marcada como `superseded`.

Foi comparado um extrator visual pré-treinado com uma galeria de recortes reais
dos campeões. A galeria usa somente a partição de treino: 29 unidades nomeadas,
dez recortes negativos de HUD e 16 IDs. Inserir exemplos por temporada passa a
ser uma atualização da galeria versionada. Não houve ajuste dos pesos desses
extratores para TFT nesta comparação.

No mesmo conjunto de desenvolvimento, entre os dez recortes de teste com nome
revisado, a primeira opção acertou 3/10 com a CNN anterior, 8/10 com MobileNetV3,
9/10 com DINOv2 a 140 pixels e INT8, e 10/10 com DINOv2 a 224 pixels. Os outros
dois recortes continuam sem identidade revisada e não contam como negativos
confirmados. A reutilização dessa partição impede tratá-la como novo teste cego.

O MobileNetV3 exportado tem 3.717.890 bytes e executou 12 recortes em mediana
37,7 ms, p95 41,9 ms, com uma thread de CPU e sem importar PyTorch. O DINOv2
INT8 tem 25 MB e levou p95 557,7 ms no mesmo tamanho de lote. Os valores são
inferência Linux local, sem captura, transporte ou voz. A opção leve está
integrada como reconhecedor diagnóstico opcional em `hm/unit_gallery.py`.
Nenhuma configuração ativa dessa galeria foi adicionada ao pacote distribuído.

O limiar fixo de similaridade 0,8 e margem entre classes 0,08 aceitou somente
1/10 unidades nomeadas no teste MobileNet, sem aceitar os dois erros. Portanto,
**8/10 primeiras opções corretas não equivalem a 8 unidades confirmadas**.
Ainda são necessárias mais vistas, cobertura dos outros 58 IDs e validação
independente de rejeição de desconhecidos, propriedade, estrelas e posição.

Itens usam seu banco de ícones próprio. `hm/equipment_identity.py` resolve
aliases somente quando há um único ID exato no catálogo de atributos ativo;
exige separação entre os dois melhores resultados e mantém itens ambíguos sem
ID. A associação à unidade vale apenas para a barra no mesmo quadro, sem
herdar o índice do marcador de outro quadro. No quadro 204, os candidatos
equipados foram Espada G.p.C. e Juramento do Protetor. Isso não constitui uma
avaliação de todos os itens. A análise integrada das imagens 193 e 204 levou
107,6 e 68,3 ms, respectivamente, com geometria previamente extraída dessas
mesmas imagens. Não foi emitido `verified_state` nem orientação estratégica.

Reprodução: `python -m training.export_unit_encoder --help` exporta os recursos
oficiais; `python -m training.evaluate_unit_gallery --help` prepara a galeria,
verifica a separação das partidas, mede a inferência e grava os hashes. Pesos e
imagens ficam no laboratório do SSD. Relatórios e fontes estão em
`docs/evidence/visual-gallery-20261004`.

Também foram corrigidas duas incompatibilidades vistas no CI Windows: os JSON
do catálogo/pesos de coaching devem preservar LF para os hashes conferirem, e
os leitores desta etapa especificam UTF-8 para nomes multilíngues. A verificação
de integridade dos arquivos permanece obrigatória.

### Galeria ampliada, revisão de rótulos e compactação — 2026-10-04

A galeria corrigida cresceu de 29 para **193 recortes de campeões**, de 17 para
**51 IDs oficiais** entre os 74 IDs do catálogo. Há também dez negativos de HUD.
Foram revisados 36 quadros de treino: 29 recortes novos vieram do YouTube de
Wasianiverson e 55 do VOD da Twitch de Dishsoap, extraídos diretamente em 1080p.
Cada fonte registra URL, tempo do vídeo, formato, hashes da imagem e dos pixels.
Os vídeos completos de cada criador permanecem numa única partição.

As nove correções substituem Elise por Camille em cinco recortes, Soraka por
Karma em um, Alistar por Ornn em um e Karma por Master Yi em dois. Foram
conferidos recortes, quadros completos, características visíveis e catálogo
sazonal. Isso continua sendo revisão pelo assistente, sem validação humana
independente. O registro de alterações está em
`docs/evidence/gallery-expansion-20261004/label-corrections.json`.

`training.export_unit_gallery_review` gera uma galeria HTML filtrável, recortes
PNG e um índice JSON com código estável, ID oficial, nome, origem e checksum.
O código da imagem depende de seus pixels e coordenadas, portanto corrigir o
nome não muda esse código. A numeração de exibição é apenas uma ordenação.
Os 193 arquivos e seus vínculos foram verificados. A galeria e um ZIP de 4,9 MB
estão no laboratório privado do SSD, sem incluir vídeos no GitHub.

O reconhecimento compara **vetores de características aprendidas** dos
recortes. Não exige igualdade pixel a pixel. Esta etapa amplia a memória de
referências: **não houve treinamento de novos pesos** nem implementação de
memória temporal de identidade. Combinar quadros consecutivos exigirá
rastreamento e invalidação após compra, venda, mudança de cena e movimento.

Foi reservado outro VOD, de Subzeroark na Twitch, para 19 novos recortes de
teste. Nenhum deles entrou na galeria. Junto aos dez recortes nomeados do teste
local reutilizado, os resultados com limiar 0,8 e margem 0,08 foram:

| Extrator | Arquivo | p95 para 12 recortes | Primeira opção correta | Candidatos aceitos / errados |
| --- | ---: | ---: | ---: | ---: |
| MobileNetV3 | 3,7 MB | 39 ms | 14/29 | 3 / 0 |
| DINOv2 completo FP32 | 88,4 MB | 779 ms | 16/29 | 2 / 0 |
| DINOv2 completo INT8 | 25,0 MB | 546 ms | 18/29 | 2 / 0 |
| DINOv2 com 6 blocos INT8 | 14,0 MB | 287 ms | 6/29 | 0 / 0 |

Medição de inferência em CPU Linux, uma thread, sem captura, transporte, voz ou
pré-processamento. Tamanho de arquivo não é consumo de RAM. No VOD novo,
MobileNet acertou a primeira opção em 10/19, DINO completo FP32 em 7/19 e INT8
em 9/19; **nenhum aceitou um candidato nesse VOD**. Os dois recortes locais sem
nome permanecem fora do denominador de acertos. Não são negativos confiáveis.

O núcleo DINO já é somente o extrator visual. A quantização reduziu o arquivo
em aproximadamente 72% e preservou melhor o resultado desta pequena avaliação.
O corte ingênuo de metade dos blocos foi **reprovado**: reduziu custo, mas perdeu
discriminação. O exportador permite reproduzir esse experimento explicitamente
com `--dinov2-blocks 6`; o padrão permanece 12. A equivalência PyTorch/ONNX do
modelo de seis blocos teve erro máximo 1,49e-7; isso valida a exportação, não a
qualidade de reconhecimento. Não houve destilação do modelo.

Todos os modelos continuam **diagnósticos, sem ativação estratégica**. Faltam
23 IDs, incluindo dez variantes de Lux, e muitos dos 51 IDs têm somente uma
vista. Também faltam validação independente, diversidade de poses/domínios,
localização robusta de recortes, memória temporal, estrelas/propriedade/hexágono
e avaliação abrangente dos itens. Recortes ambíguos ou mal centralizados foram
excluídos; estas métricas não medem a cobertura do detector de barras.

Reprodução: usar `unit-identity-corrected-20261004.json` como baseline,
`unit-gallery-expanded-20261004.json` para a galeria e
`unit-gallery-challenge-20261004.json` para incluir o novo VOD de teste, todos
em `configs/training`, com `--images datasets`. Executar
`python -m training.evaluate_unit_gallery --help` e
`python -m training.export_unit_gallery_review --help` para os argumentos.
Relatórios, previsões, cobertura por ID, códigos e fontes estão em
`docs/evidence/gallery-expansion-20261004/summary.json` e arquivos adjacentes.

Referência técnica de compactação:
[quantização no ONNX Runtime](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html).

## Recortes e vetores em Rust — 05/10/2026

Por solicitação do usuário, esta nova implementação é nativa em Rust.
`image-preprocess::unit_features` extrai regiões RGB/RGBA/BGRA com validação
de limites e stride, redimensiona, produz escala de cinza, calcula uma hipótese
de primeiro plano e compara vetores. Não contém IDs ou regras sazonais.
`tools/unit-features-lab` carrega o encoder pelo ONNX Runtime nativo, gera
vetores e grava a galeria em float32 little-endian com IDs em JSON.
Não usa interpretador Python nem OpenCV. A biblioteca ONNX Runtime é uma
dependência nativa carregada explicitamente, não está embutida no executável.

O fluxo é: quadro → região do personagem → preparação → encoder → vetor →
comparação com referências. Os vetores das referências são calculados uma vez;
cada novo recorte ainda precisa ser processado. Isso é reconhecimento por
características, não igualdade de pixels. O método de
[DINOv2](https://arxiv.org/abs/2304.07193) é uma referência para representações
visuais aprendidas. O descritor de gradientes experimental é inspirado em
[HOG](https://lear.inrialpes.fr/people/triggs/pubs/Dalal-cvpr05.pdf), mas não
implementa o detector HOG/SVM do artigo.

A máscara Rust remove cores semelhantes às bordas somente quando conectadas
às bordas. É uma aproximação, não segmentação semântica nem GrabCut. A inspeção
dos recortes mostrou linhas do tabuleiro preservadas e partes de personagens
removidas. O estudo preliminar anterior com GrabCut executava C++ através de
Python; os números desse algoritmo não medem a implementação Rust atual.
Mudar a linguagem, isoladamente, não comprova redução do custo de segmentação.

### Avaliação nativa

Mesma galeria de 193 recortes nomeados + 10 negativos, 51 IDs; 29 recortes
nomeados de teste, incluindo os 19 do VOD separado. Limiar 0,8 e margem 0,08
mantidos, sem ajuste aos resultados. Sem atualização de pesos. Rótulos revisados
pelo assistente, sem validação humana independente.

| Preparação e vetor | Primeira opção correta | Aceitos / errados no teste | Mediana / p95 para 12 recortes |
| --- | ---: | ---: | ---: |
| RGB + MobileNet | 12/29 | 3 / 0 | 54,6 / 60,4 ms |
| Cinza + MobileNet | 10/29 | 4 / 0 | 54,7 / 55,8 ms |
| Máscara colorida + MobileNet | 14/29 | 3 / 0 | 68,2 / 99,8 ms |
| Máscara cinza + MobileNet | 8/29 | 4 / 1 | 60,1 / 61,5 ms |
| Gradientes cinza | 9/29 | 3 / 0 | 13,0 / 13,6 ms |
| Gradientes com máscara | 10/29 | 1 / 0 | 14,1 / 14,4 ms |

RGB e máscara colorida não aceitaram nenhuma identidade no VOD separado.
Na validação pequena de três recortes, máscara colorida caiu de 3/3 para 2/3
em relação ao RGB; gradientes sem máscara aceitaram uma identidade errada.
Portanto, a máscara não demonstrou melhoria robusta e os gradientes não podem
substituir o encoder neste estado. Cinza ainda alimenta três canais do modelo,
portanto não reduz automaticamente seu custo neural.

Medição em CPU Linux, uma thread, dez repetições após aquecimento. Inclui
preparação dos recortes já na memória, extração dos vetores e comparação.
Exclui captura, localização/extração inicial dos recortes, transporte, voz e
renderização. Não é FPS do Windows. O redimensionamento Rust é bilinear;
o baseline anterior usava bicúbico do Pillow. Comparações de preparações devem
usar a linha RGB desta execução, não atribuir diferenças à linguagem.

A galeria neural contém 203 × 576 floats: 467.712 bytes, sem contar encoder,
metadados ou memória do runtime. A máscara colorida levou mediana de 5,2 ms
para 12 recortes; a maior parte do custo permaneceu na extração neural.

O módulo é reutilizável pela captura nativa, mas esta entrega é um laboratório
executável: não altera o observador ativo nem conecta novas identidades às
dicas. Todos os candidatos continuam `identity_verified=false`.
Ainda faltam localização robusta, segmentação validada, cobertura/diversidade
de personagens, associação de itens e confirmação temporal.

### Reprodução e evidências

Compilar com Rust >= 1.88:

```sh
cargo build --locked --release --manifest-path tools/unit-features-lab/Cargo.toml
```

Executar `agente-tft-unit-features-lab` com os argumentos obrigatórios:
`--annotations configs/training/unit-gallery-challenge-20261004.json`,
`--images datasets`, `--reference <diretório do catálogo selado>`,
`--encoder <encoder.onnx MobileNet>`, `--onnxruntime <biblioteca nativa>`,
`--size 224` e `--output <diretório novo>`.
No Windows, fornecer o caminho da DLL compatível do ONNX Runtime.
O laboratório verifica hashes das imagens, pixels e catálogo, regiões válidas
e separação de fontes entre treino, validação e teste.

Relatório e previsões: `docs/evidence/vector-segmentation-20261004/`.
Imagens, encoder e galerias binárias permanecem no SSD privado.
Nove testes da biblioteca e dois do laboratório passaram localmente.
O workflow `Native unit features` executa esses contratos em Linux e Windows;
esses testes não dependem dos modelos ou dos vídeos privados e não substituem
uma medição de inferência/captura no Windows.

## Recorte combinado com contorno — 05/10/2026

Comparação solicitada pelo usuário, implementada inteiramente em Rust, com
o mesmo encoder MobileNet, galeria, partições, limiar 0,8 e margem 0,08.
O contorno é a borda interna de quatro vizinhos da máscara aproximada anterior;
não inclui automaticamente o retângulo externo do recorte. Não é uma silhueta
verificada: linhas do tabuleiro, cursor e efeitos visuais ainda aparecem nele.

Três variantes novas foram fixadas antes da execução:

- RGB com traço preto de um pixel sobre a borda da máscara.
- RGB com fundo neutralizado e o mesmo traço.
- Vetor neural do RGB original concatenado com descritor de gradientes do
  contorno binário. Ambos normalizados, ponderados por raiz de 0,8 e raiz de
  0,2: o cosseno resultante equivale a 80% da similaridade de cor/aparência e
  20% da similaridade de contorno. Não houve procura de pesos no teste.

Uma imagem sem vetor válido em qualquer ramo da fusão é recusada; o código
não muda silenciosamente os pesos para aproveitar só o outro ramo.
Os seis hashes de galerias do experimento anterior permaneceram idênticos
após extrair a rotina compartilhada de máscara, preservando os baselines.

| Variante | Primeira opção correta / 29 | Aceitos / errados | VOD separado: acertos / 19 | Mediana / p95 para 12 recortes |
| --- | ---: | ---: | ---: | ---: |
| Recorte RGB | 12 | 3 / 0 | 8 | 53,8 / 59,3 ms |
| Recorte com fundo neutralizado | 14 | 3 / 0 | 8 | 57,8 / 59,5 ms |
| Recorte RGB + contorno desenhado | 11 | 4 / 0 | 6 | 58,3 / 60,5 ms |
| Fundo neutralizado + contorno desenhado | 10 | 1 / 0 | 4 | 58,5 / 60,0 ms |
| Vetores de RGB + contorno, 80/20 | 15 | 2 / 0 | 7 | 66,1 / 67,2 ms |

A fusão melhorou quatro recortes locais e piorou um do VOD, comparada ao RGB.
As correções foram uma Rek'Sai e três Cinderlings; a piora foi Veigar.
Assim, a melhora agregada de 12/29 para 15/29 não demonstra melhora geral de
campeões em outro vídeo. A fusão não aceitou nenhuma identidade no VOD separado
nem nos três recortes nomeados de validação. O contorno desenhado aceitou uma
identidade correta no VOD, mas reduziu a acurácia de primeira opção. Não há
base para promover qualquer dessas variantes ao reconhecimento ativo.

No pequeno conjunto de validação, as três variantes novas acertaram a primeira
opção em 3/3. Isso não calibra a confiança: a fusão altera a distribuição dos
escores e precisaria de validação maior antes de escolher limiares. Sem novos
pesos neurais, sem confirmação temporal e sem alteração nas dicas.

O vetor combinado tem 1.224 valores e a galeria ocupa 993.888 bytes, contra
467.712 bytes no RGB. Nesta execução, a fusão adicionou aproximadamente 12,3 ms
por lote em relação ao RGB. Tempos incluem preparação/extração/comparação em
CPU Linux e excluem captura, localização inicial, exibição e voz. As variações
entre execuções anteriores e esta não são atribuídas a otimização de código.

Evidências: `docs/evidence/vector-contours-20261005/`, incluindo as mudanças
de previsão por recorte. As prévias RGB, sobreposição e contorno binário foram
inspecionadas e permanecem no SSD privado. Reprodução pelo mesmo comando do
laboratório, usando um diretório de saída novo. Treze testes locais passaram:
dez da biblioteca e três do laboratório, incluindo preservação da cor interna,
ausência de contorno em imagem uniforme e equivalência da fusão ponderada.
