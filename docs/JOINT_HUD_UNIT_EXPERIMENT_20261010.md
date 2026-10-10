# Mapeamento conjunto do HUD e dos campeões — 10/10/2026

Experimento isolado no SSD: `/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/experiments/joint-hud-unit-20261010/`.

## O que foi marcado

- Sete classes de localização: corpo de campeão, estágio, ouro, nível, XP, valor de HP no painel de jogadores e card ocupado da loja.
- Os corpos vêm de caixas de origem confirmadas por usuário ou por painel do jogo. Há 45 caixas independentes no treino, dez na validação e quatro no teste; três variações de recorte das caixas de treino geram 135 imagens, não 135 cenas independentes.
- As marcas de HUD vêm do layout 1920×1080 e dos pixels dos círculos do painel. Foram auditadas nas prévias com caixas amarelas. Não são leituras dos números ou identidades dos campeões.
- Cada fonte de vídeo pertence a apenas uma divisão: treino, validação ou teste. O conjunto final tem 201 recortes: unidades revisadas mais regiões do topo, rodapé e painel lateral. Quadros com loja encoberta ou seleção de itens não foram rotulados como loja normal.
- As regiões de HUD são separadas dos recortes de corpos para não converter campeões visíveis sem revisão em exemplos negativos. O jogo completo continua necessário para avaliar o reconhecimento real.
- `previews/` contém o quadro original com caixas amarelas de HUD e verdes de campeões revisados. Essas prévias não são previsões dos modelos.

## Limites do experimento

O detector de `champion_body` encontra um corpo genérico; não diz se é Ornn, Rakan ou outro campeão. O nome confirmado fica no índice de revisão e não foi usado para criar uma classe com poucas poses. O valor do HP, ouro, XP e estágio também exige leitura posterior dos recortes. O painel pode mudar de posição conforme resolução, escala de interface e transmissões com overlays; por isso, a avaliação usa vídeos reservados e relata os erros por classe.

Os scripts de construção, treino e avaliação são `training/build_joint_hud_unit_experiment.py`, `training/train_joint_hud_unit_experiment.py`, `training/evaluate_joint_hud_unit_experiment.py` e `training/preview_joint_hud_unit_experiment.py`. Pesos, vídeos e imagens grandes permanecem fora do Git.

## Resultados dos vídeos reservados

O YOLO11n recebeu 20 épocas; o Faster R-CNN MobileNetV3 320 recebeu 15 épocas com backbone COCO congelado e nova cabeça de oito classes, incluindo fundo. Os dois usaram o mesmo conjunto e limiar de confiança de 0,15 no comparativo de caixas. Os tempos abaixo pertencem ao protótipo com regiões e mosaicos; não são a taxa de quadros do aplicativo.

| Detector | Recortes: caixas revisadas encontradas | Cena completa: HUD | Cena completa: corpos revisados | Caixas de corpo por quadro completo |
| --- | ---: | ---: | ---: | ---: |
| YOLO11n | 34/46 | 30/42 | 2/4 | 12–19 |
| Faster R-CNN | 46/46 | 42/42 | 2/4 | 18–35 |

Nos 13 recortes do teste, o YOLO encontrou as quatro caixas de corpo, oito cards da loja e 22/24 áreas de HP; com confiança ≥ 0,15 não encontrou estágio, ouro, nível nem XP. O Faster encontrou todas as 46 caixas revisadas nesse teste pequeno. Na cena completa, o Faster achou todas as 42 áreas de HUD marcadas, mas as prévias também mostram várias caixas verdes sobre pedras, plantas, interface e outros elementos que não são campeões. O YOLO também apresentou caixas indevidas e perdeu algumas áreas do HUD. Os quatro corpos revisados são insuficientes para estimar precisão geral; outros corpos visíveis não estão todos anotados. Não há evidência para substituir o reconhecedor do aplicativo por qualquer um desses pesos.

Os relatórios reproduzíveis estão em `runs/joint-yolo11n/test-report.json`, `runs/joint-yolo-patch-report.json`, `runs/joint-faster-patch-report.json` e `previews/predictions-{yolo,faster}/report.json`. As imagens de cena completa mostram previsões amarelas do HUD, previsões verdes de corpo e caixas vermelhas de referência dos quatro corpos do teste.

**Próxima mudança necessária nos dados:** anotar integralmente todos os corpos e regiões negativas em quadros completos de partidas separadas, inclusive cenários e overlays que receberam caixas falsas. Manter o mapeamento do HUD como sinal estrutural e avaliar o nome do campeão em etapa própria, com múltiplas poses por identidade. O resultado atual demonstra que o HUD pode ser localizado; ainda não demonstra reconhecimento confiável dos campeões na partida inteira.

Arquivos locais de outro trabalho preservados: `training/materialize_champion_restart.py`, `training/prepare_champion_restart.py` e `training/train_champion_yolo_restart.py`.
