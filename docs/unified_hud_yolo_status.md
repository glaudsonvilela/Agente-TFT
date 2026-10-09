# Experimento YOLO para o HUD do TFT

Registro de 2026-10-09. O treino roda somente no laboratório privado do SSD. Os vídeos, imagens, pesos e ambientes Python não entram no repositório nem no instalador.

O construtor `training/build_unified_hud_yolo.py` combina 222 quadros previamente revisados com recortes do painel de jogadores provenientes de vídeos separados. A versão atual contém 1.215 imagens; as fontes de treino, validação e teste são registradas no arquivo privado `audit.json`. São oito classes de **localização**: unidade no tabuleiro, unidade na reserva, linha de jogador, avatar de jogador, estágio, ouro, nível e oferta da loja. As linhas e avatares dos adversários são marcados por caixas retangulares localizadas a partir de círculos detectados na imagem.

As caixas do tabuleiro e da reserva vieram de revisão visual anterior, mas a cobertura é incompleta. As caixas de HUD vêm de projeção de layout e de uma regra visual; as de avatares são propostas por Hough. Nenhuma dessas propostas equivale a uma auditoria humana independente de cada quadro. O teste mantém fontes diferentes fora do treino.

Este modelo ainda não lê nomes de campeões, itens, nomes dos jogadores, valores de vida ou números do HUD. Essas leituras exigem rótulos próprios ou leitores associados. Vídeos sem anotações confiáveis não são convertidos em rótulos de campeões por previsão do próprio modelo. Um índice de 100% no treino não demonstraria 100% em partidas novas; o objetivo é medir por classe em fontes separadas e ampliar as anotações onde houver falhas.

O treino CUDA usa a GTX 1060 de 3 GB, resolução de 640 px e lote 6. A utilização instantânea varia; não há controle exato que a fixe entre 90% e 95%. O monitor aberto no Ubuntu mostra utilização, VRAM, temperatura, mAP50, revocação e precisão do conjunto de validação.
