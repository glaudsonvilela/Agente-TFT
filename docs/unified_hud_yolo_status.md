# Experimento YOLO para o HUD do TFT

Registro de 2026-10-09. O treino roda somente no laboratório privado do SSD. Os vídeos, imagens, pesos e ambientes Python não entram no repositório nem no instalador.

O construtor `training/build_unified_hud_yolo.py` combina 222 quadros previamente revisados com recortes do painel de jogadores provenientes de vídeos separados. A versão atual contém 1.215 imagens; as fontes de treino, validação e teste são registradas no arquivo privado `audit.json`. São oito classes de **localização**: unidade no tabuleiro, unidade na reserva, linha de jogador, avatar de jogador, estágio, ouro, nível e oferta da loja. As linhas e avatares dos adversários são marcados por caixas retangulares localizadas a partir de círculos detectados na imagem.

As caixas do tabuleiro e da reserva vieram de revisão visual anterior, mas a cobertura é incompleta. As caixas de HUD vêm de projeção de layout e de uma regra visual; as de avatares são propostas por Hough. Nenhuma dessas propostas equivale a uma auditoria humana independente de cada quadro. O teste mantém fontes diferentes fora do treino.

Este modelo ainda não lê nomes de campeões, itens, nomes dos jogadores, valores de vida ou números do HUD. Essas leituras exigem rótulos próprios ou leitores associados. Vídeos sem anotações confiáveis não são convertidos em rótulos de campeões por previsão do próprio modelo. Um índice de 100% no treino não demonstraria 100% em partidas novas; o objetivo é medir por classe em fontes separadas e ampliar as anotações onde houver falhas.

O treino CUDA usa a GTX 1060 de 3 GB, resolução de 640 px e lote 6. A utilização instantânea varia; não há controle exato que a fixe entre 90% e 95%. O monitor aberto no Ubuntu mostra utilização, VRAM, temperatura, mAP50, revocação e precisão do conjunto de validação.

## Resultado medido após o treino

O treino v2 encerrou na época 44 por estagnação. O melhor mAP50 da validação foi 97,48%, mas a avaliação separada em 214 imagens de teste caiu para **69,95% de mAP50** (precisão 54,26%; revocação 88,50%). A diferença mostra que a validação era otimista para as fontes novas.

| Categoria | mAP50 no teste | Precisão no teste | Instâncias de teste |
| --- | ---: | ---: | ---: |
| Unidade no tabuleiro | 46,24% | 34,12% | 22 |
| Unidade na reserva | 87,09% | 91,68% | 9 |
| Linha de jogador | 94,05% | 90,76% | 1.357 |
| Avatar de jogador | 98,28% | 92,15% | 1.357 |
| Estágio | 45,03% | 31,39% | 9 |
| Ouro | 75,48% | 31,54% | 9 |
| Nível | 68,20% | 31,82% | 9 |
| Oferta da loja | 45,21% | 30,62% | 29 |

As 1.357 caixas de cada categoria do painel foram propostas pelo detector de círculos; estes números medem concordância com a proposta, não a identificação confirmada de cada adversário. O teste de tabuleiro, reserva e HUD inteiro tem poucas caixas, além de anotações incompletas. O modelo permanece fora do software.
