# L3 — revisão do caminho completo do mapa

Base de código: `d99fa05793adb86af0b4b30f3be3866fdfbc79cf` (PR #32).
Não substitui U1, L1, L2, B1, S4 ou Tesseract. Os pacotes congelados continuam
byte a byte; módulos L2 são importados por um adaptador que confere seu manifesto.
Código novo em `training/uimap_path_l3`, testes dedicados e um launcher de SSD.

## Pedido e caminho examinado

O usuário pediu tratar os problemas conectados de uma só vez, principalmente pixels
fora do lugar, evitando calibrar um campo e deixar o próximo quebrado. Foram lidos
os módulos L2 de geração, modelo, perda, avaliação, refinamento, exportação,
execução, decisão e launcher; também o perfil banco/tabuleiro e o contrato Rust
`perception-board`. Isto não é uma revisão semântica de todos os arquivos do projeto.

O `comparison.txt` L2 do usuário (SHA-256
`02210578d32ac5c773934437c692651008a91b682f8bed29c92bea984ac72233`)
mediu 1,80/1,99 ms no núcleo ONNX, 27,97 ms de preparo e 17,31 ms no
pós-processamento/refinamento (medianas das duas últimas etapas). Não somar
percentis para inventar uma latência total. O total cronometrado foi 48,03/55,94 ms.

## Achados e correções conectadas

| Ponto | Evidência no caminho antigo | Tratamento L3 |
|---|---|---|
| Suporte da saída | Grid L2: `(i+0.5)/N`. Em 48 linhas, y máximo = 1068,75 px em 1080. A seed da loja termina em y=1075. Logo há 6,25 px de erro mínimo para essa borda, antes de qualquer falha de treino. x vai de 12 a 1908. | Novo contrato de nós 0..1 e alvos espaciais bilineares com expectativa igual ao alvo. Não é clipping das caixas antigas. Requer pesos de contrato novo. |
| Alvo junto à borda | A gaussiana espacial é truncada pela malha; perto da extremidade sua média pode deslocar o alvo para dentro. | Alvo em quatro nós adjacentes; testes de massa e expectativa também nos extremos. |
| Geração/preparo | L2 treina em imagem já reduzida; o teste refaz transformações em resolução nativa. Margens de contexto eram arredondadas separadamente nas duas escalas. | Uma renderização canônica em 1920x1080, seguida do mesmo resize. O retângulo segue a escala efetiva do tile, não uma margem arredondada independente. |
| Duplicação de decode | O laço de diagnóstico do treinador L2 abre o original e chama `input_path`, abrindo-o novamente. O runtime ONNX L2 já abre uma vez; não atribuir a ele esse bug. | `PreparedFrame`: RGB e tensor de uma única abertura, reutilizados nas comparações. API para receber RGB existente, ainda sem ligação à captura real. |
| Custo de luma | O refinador L2 calcula a tela inteira antes de verificar se algum painel é elegível. A combinação de tipos cria temporários float64. | Luma somente nas faixas examinadas, sob demanda. Mesma aritmética e propostas verificadas por igualdade. |
| Significado das bordas | As seeds são envelopes aproximados, não necessariamente molduras físicas. Uma borda forte pode ser de outro objeto. No teste do usuário houve dez pioras entre 55 ajustes. | Refinamento continua medido e comparado, mas seu resultado é apenas diagnóstico, separado do mapa entregue. Não escolher bordas por gabarito. |
| Caudas de erro | A média geral não revela cada canto ruim. Em `context_paste`, o banco L2 do usuário tinha p95 escalar de 50,05 px, apesar do agregado menor. | Erro máximo por painel e gates por modo, junto dos números antigos. Sem esconder inversões, ausência ou piores exemplos. |
| Visibilidade | Um exemplo oculto da loja foi aceito no resultado do usuário; não há probabilidade calibrada. | Negativos visuais de desenvolvimento, com hashes e origem explícita; nada de usar todas as previsões como labels. Ainda não há certificação semântica. |
| Consumidor do mapa | Confiança e retângulo válido não provam recorte preciso. | IDs de frame e espaço, escopo do painel, bounds antes do arredondamento e contrato separado para precisão. Nenhum consumidor real é ativado. |
| Tabuleiro | Localizar envelopes de banco/loja não localiza os pontos no chão. `assign_detections` legado usa centro de bbox. | Não encaminhar essas caixas à associação legada. Geometria planar tem testes de ida/volta, mas o estado do tabuleiro permanece sem transform/células por falta de landmarks observados. |

## Duas revisões locais, ambas preservadas

A primeira tentativa L3, inicializada do zero, regrediu no contexto colado.
Não foi promovida. A revisão publicada transfere os pesos L2 preservados e troca
explicitamente o grid antes de treinar. As previsões L2 não são rótulos.
O estado inicial, pesos finais, hashes e seleção por validação ficam registrados.
A revisão de desenho foi informada pelo primeiro ensaio; não alegar pesquisa cega
nem validação em nova partida. O segundo ensaio usa outro conjunto gerado, ainda
com as mesmas quatro imagens-fonte reservadas para desenvolvimento/teste.

Resultado local da revisão publicada (L2 local preservado, NÃO pesos do PC do usuário):

| Métrica no comparativo pareado | L2 | L3 |
|---|---:|---:|
| Erro médio banco (px) | 8,12 | 9,54 |
| P95 do pior canto banco (px) | 38,36 | 76,31 |
| Erro médio loja (px) | 7,11 | 4,55 |
| P95 do pior canto loja (px) | 39,60 | 23,46 |
| Exemplos ocultos aceitos banco/loja | 0 / 4 | 0 / 1 |

A melhora não é uniforme. L3 NÃO substitui L2 como referência geral. O banco tem
outliers importantes no contexto colado; uma falsa proposta de loja permanece.
Precisão em frames naturais continua sem gabarito; nenhuma célula está certificada.

O refinador por faixas reproduziu exatamente as propostas/traços L2 nos 40 JPEGs
locais: mediana 8,48 -> 0,94 ms. São medições locais sequenciais e de um componente,
não benchmark do PC do usuário nem melhoria de toda a aplicação nessa proporção.
Rede: 27.726 parâmetros; PyTorch residente local p50/p95 3,11/3,76 ms.
Preparação de dados: 40,95 s; treino de 1400 passos: 165,56 s; passo escolhido 400.
ONNX ausente localmente; a integração deve ser conferida no workflow dedicado.

## Supervisão e preservação

Treino/validação/teste mantêm separação por fonte. Três negativos foram examinados
visualmente: desktop/cliente (treino), tela preta (validação), seleção inicial sem
banco/loja (teste). São seeds de desenvolvimento feitas nesta revisão, NÃO labels
fornecidos pelo usuário nem evidência de generalização a todas as telas. Não publicar
as imagens no Git. Os outros labels vêm das transformações conhecidas de envelopes.

Nenhum preço, texto, campeão, item ou valor de HP é usado para acertar coordenadas.
Não há nova instalação, modelo grande, serviço no BigBANANA ou treinamento contínuo.
Os 22 apontamentos históricos não foram declarados corrigidos. O CI dedicado deve
executar as suítes congeladas L1/L2 com ONNX, além da suíte nova e da revisão estrutural.

## Comando no Ubuntu

Na branch publicada, rodar `bash scripts/probe_match001_ui_map_path.sh`.
O launcher reutiliza ambientes B3/L1 e verifica UUID/montagem do SSD. Localiza o L2
mais recente, verifica o selo completo e compara os 40 mesmos arquivos/timestamps.
Uma referência corrompida não é ignorada para escolher outra. Pode-se explicitar
`UI_MAP_L2_RUN` e os diretórios pelos parâmetros ambientais do launcher.

Saída exclusiva: `/mnt/sherlock-ssd/Agente-TFT/ui-map-path-l3/match-001-ui-map-l3.XXXXXXXX`.
O comando mede preparação, chamada neural, decisão e refinamento diagnóstico em
separado; o total sem refinamento é rotulado como tal. `comparison.txt` e `viewer.html`
reúnem a comparação. Não se reinicia B3/DINO, nem Tesseract, nem FFmpeg por campo.

Estado final obrigatório: nenhuma promoção, nenhum GameState alterado, tabuleiro
sem associação ao chão, runtime Rust e aprendizado contínuo ainda não conectados.
Publicação/CI de código não significa autorização para usar o modelo nos leitores.
