# Comparação de detectores grandes para TFT — 10/10/2026

## Pergunta

Um detector maior melhora a localização de corpos de campeões e regiões do HUD em partidas que não participaram do treino?

## Dados e protocolo

- Mesmo conjunto `joint-hud-unit-20261010` para os dois modelos: 169 recortes de treino, 19 de validação e 13 de teste. A separação é por vídeo, não por quadro.
- Sete classes: corpo genérico de campeão, estágio, ouro, nível, XP, HP do painel de jogadores e card da loja.
- Comparação em quatro quadros inteiros de vídeos reservados, com 42 caixas de HUD e quatro corpos revisados. O pipeline usa as mesmas regiões do HUD e mosaicos de 512 px para o tabuleiro nos dois modelos.
- O limiar de confiança da comparação é 0,15; uma referência é encontrada quando a classe coincide e a sobreposição das caixas (IoU) é pelo menos 0,5. Todas as caixas previstas são desenhadas, inclusive as potencialmente falsas.
- As quatro caixas de corpo são insuficientes para medir precisão no quadro inteiro: existem outros corpos visíveis sem anotação completa. O relatório mostra o número de caixas propostas e cada acerto individualmente.

## Modelos

- YOLO26x: pesos abertos pré-treinados, ajuste de 20 épocas, imagem 640 px, lote 1, AdamW, taxa inicial 0,0002, sem mosaic nem mixup.
- RF-DETR Large: pesos abertos pré-treinados, ajuste de 20 épocas, lote 1, acumulação 1, checkpointing de gradientes, sem escalas expandidas nem EMA. Usa o mesmo conjunto convertido por links simbólicos ao formato esperado pela biblioteca.
- Os pesos RF-DETR 2XL têm licença PML 1.0 e dependem de um contrato de plataforma. Sem esse contrato, o experimento usa a variante Large, distribuída sob Apache 2.0.

Ambos os treinos usam a GTX 1060 de 3 GB, em sequência. Os pesos, quadros, dependências isoladas e registros ficam em `/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/experiments/large-detector-20261010/` e não entram no Git.

## O que este treino não mede

A classe `champion_body` encontra uma unidade, mas não identifica seu nome. A classe `gold_display` encontra uma área do HUD, mas não lê o valor. As 106 capturas com nomes confirmados pelo usuário estão num acervo separado; nenhuma previsão do modelo foi tratada como rótulo. O reconhecimento de identidades exige múltiplas poses independentes e uma avaliação própria em partidas inéditas.

## Resultados

Os dois treinos terminaram as 20 épocas, e `training/benchmark_large_hud_detectors.py` comparou os melhores pesos de validação em quatro quadros completos dos vídeos reservados. O tempo inclui vários recortes do mesmo quadro, desenho e sincronização da GPU; não é o FPS do aplicativo.

| Detector | HUD encontrado | Corpos revisados encontrados | Caixas de corpo por quadro | Tempo por quadro completo |
| --- | ---: | ---: | ---: | ---: |
| YOLO11n anterior | 30/42 | 2/4 | 12–19 | — |
| Faster R-CNN anterior | 42/42 | 2/4 | 18–35 | — |
| YOLO26x | 32/42 | 3/4 | 1–20 | 1,4–3,7 s |
| RF-DETR Large | 42/42 | 2/4 | 7–21 | 1,4–3,1 s |

O RF-DETR Large localizou todas as caixas de HUD deste teste pequeno. O YOLO26x localizou três dos quatro corpos revisados, um a mais que o RF-DETR Large. Nenhum resultado comprova reconhecimento confiável dos campeões: ambos ainda marcam partes do cenário, interface ou avatar como corpo, e a anotação incompleta impede calcular a precisão do corpo em quadros inteiros. Na cena `8W7Wfnf36M8-1590-full.png`, nenhum dos dois alcançou IoU 0,5 com a caixa revisada, embora o RF-DETR desenhe algumas caixas sobre inimigos visíveis.

As pontuações de validação em recortes foram mAP50 de 0,739 para YOLO26x e de 0,920 na última época do RF-DETR Large. São apuradas por avaliadores diferentes e em apenas 19 recortes de validação; a comparação mais relevante é a tabela de quadros inéditos acima. Os relatórios por quadro e imagens com caixas ficam em `eval-yolo26x/` e `eval-rfdetr-large/` no diretório do experimento no SSD.

**Decisão:** não substituir ainda o reconhecedor do aplicativo. Para escolher um detector de campeões, é preciso anotar todos os corpos, aliados e inimigos, inclusive banco, em quadros completos de várias partidas reservadas. O recorte usado aqui ainda exclui parte da faixa superior do tabuleiro, onde alguns inimigos aparecem. O nome do campeão exige outra avaliação, com rótulos de identidade.
