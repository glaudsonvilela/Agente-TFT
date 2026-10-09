# Revisão dos treinos YOLO de inimigos e itens — 2026-10-09

## Proveniência

- Os vídeos foram separados por partida antes da amostragem. Nenhum quadro da
  partida de teste entrou no treino.
- As caixas de inimigos foram propostas pela geometria de barras vermelhas.
  Elas **não são rótulos humanos** e não contêm a identidade do campeão.
- Os itens partiram de 193 artes oficiais fixadas no catálogo. Os exemplos de
  treino simulam compressão, tamanho do HUD e, no segundo ensaio, contadores.
  Treino e validação simulada compartilham a arte de origem de cada classe.
- Vídeos, recortes, modelos e caminhos de mídia ficam fora do Git.

## Inimigos no tabuleiro

| Ensaio | Treino | Teste de outra partida | mAP50 no mesmo teste |
| --- | ---: | ---: | ---: |
| Modelo inicial | 51 quadros, 222 propostas | 36 quadros, 170 propostas | 0,731 |
| Mais fontes, após revisão visual | 137 quadros, 726 propostas | 36 quadros, 170 propostas | 0,738 |

O ganho de 0,007 mede concordância com propostas automáticas, não acerto real
de campeões. Dois vídeos adicionais tinham barras em outra cor; neles, efeitos
visuais geravam falsos exemplos de inimigos. Esses vídeos foram excluídos do
segundo treino. O segundo processo terminou por sinal externo durante a época
8; a comparação usa o melhor checkpoint salvo até a época 7. Não houve base
para substituir o detector em uso.

## Itens

O primeiro ensaio de adaptação ao HUD usou 6.948 imagens simuladas de treino e
1.158 de validação, em 193 classes. A validação simulada chegou a 100% de
top-1. Isso **não** equivale a 100% de acerto em partidas.

Em seis recortes de duas partidas, cinco previsões do primeiro ensaio parecem
corresponder à arte observada. A sexta, parcialmente coberta por um contador,
teve confiança baixa e arte incompatível. Um novo treino simulou números sobre
os ícones; manteve o resultado sintético, mas passou a errar esse sexto recorte
com confiança maior. Portanto, o modelo com contadores não foi promovido.

A ferramenta `training/audit_item_hud_crops.py` gera uma folha com recorte,
previsão e arte oficial. O arquivo marca explicitamente que previsões não são
rótulos. A precisão real ainda precisa de recortes rotulados e verificados em
partidas independentes; repetir transformações da mesma arte não resolve essa
lacuna.
