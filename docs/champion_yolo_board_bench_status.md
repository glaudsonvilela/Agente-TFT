# Reconhecimento YOLO de unidades no tabuleiro e na reserva

Registro de 2026-10-09. Este experimento está isolado do aplicativo. Os vídeos, recortes, ambientes Python e pesos ficam no SSD em `diagnostics/fresh-champion-corpus-20261008`; nenhum deles faz parte do repositório ou do instalador.

## Dados medidos

- O catálogo Set 18.3 usado neste experimento contém 65 nomes distintos, incluindo criaturas do conjunto. Os nomes no catálogo não demonstram que o modelo os reconhece.
- As anotações existentes contêm 184 imagens de treino, 6 de validação e 32 de teste, separadas por partida. Há 642 caixas com nome no treino: 384 marcadas como tabuleiro, 138 como reserva e 120 sem zona confirmada. Nos dados de teste, somente 7 caixas de reserva têm nome confirmado. A origem são anotações revisadas pelo assistente, não uma avaliação humana independente; alguns bonecos visíveis não foram marcados.
- Todos os 65 nomes aparecem pelo menos uma vez no treino, mas 31 têm menos de 10 recortes. Kayle, Xayah e Kha'Zix têm apenas um exemplo cada. Dez poses distintas por campeão ainda não foram verificadas.
- O primeiro YOLO de detecção com 65 classes, treinado por 15 épocas em 512 px, teve precisão, revocação e mAP iguais a zero na validação. No segundo treino, em 640 px, o checkpoint da época 10 registrou mAP50 de 1,46% e revocação de 6,44% nas 32 caixas da validação. Isso é insuficiente para integrar no software.
- A medição separada de tabuleiro e reserva foi implementada no laboratório. Para o primeiro modelo, nenhuma das 12 caixas de reserva da validação nem as 7 do teste recebeu nome correto com IoU ≥ 0,5. A validação do segundo modelo por zona ainda está pendente.
- A GTX 1060 de 3 GB está sendo usada pelo treino CUDA, com amostras recentes entre 89% e 98% de utilização. Não há treinamento silencioso em CPU.

## Próximo passo do experimento

Concluir a avaliação separada por zona do segundo treino. Treinar um YOLO para localizar unidades em tabuleiro e reserva e outro YOLO para classificar os recortes permite medir separadamente localização e identidade. Os recortes para essa comparação já foram preparados, mas os resultados ainda não existem. Ampliar os exemplos reais das classes raras requer confirmar manualmente as identidades nos vídeos novos; previsões do modelo não serão convertidas automaticamente em rótulos.
