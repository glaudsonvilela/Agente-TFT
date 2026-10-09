# Reconhecimento YOLO de unidades no tabuleiro e na reserva

Registro de 2026-10-09. Este experimento está isolado do aplicativo. Os vídeos, recortes, ambientes Python e pesos ficam no SSD em `diagnostics/fresh-champion-corpus-20261008` e `diagnostics/scene-training-20261009`; nenhum deles faz parte do repositório ou do instalador.

## Dados medidos

- O catálogo Set 18.3 usado neste experimento contém 65 nomes distintos, incluindo criaturas do conjunto. Os nomes no catálogo não demonstram que o modelo os reconhece.
- As anotações existentes contêm 184 imagens de treino, 6 de validação e 32 de teste, separadas por partida. Há 642 caixas com nome no treino: 384 marcadas como tabuleiro, 138 como reserva e 120 sem zona confirmada. Nos dados de teste, somente 7 caixas de reserva têm nome confirmado. A origem são anotações revisadas pelo assistente, não uma avaliação humana independente; alguns bonecos visíveis não foram marcados.
- Todos os 65 nomes aparecem pelo menos uma vez no treino, mas 31 têm menos de 10 recortes. Kayle, Xayah e Kha'Zix têm apenas um exemplo cada. Dez poses distintas por campeão ainda não foram verificadas.
- O primeiro YOLO de detecção com 65 classes, treinado por 15 épocas em 512 px, teve precisão, revocação e mAP iguais a zero na validação. No segundo treino, em 640 px, o checkpoint da época 10 registrou mAP50 de 1,46% e revocação de 6,44% nas 32 caixas da validação. Isso é insuficiente para integrar no software.
- A medição separada de tabuleiro e reserva foi implementada no laboratório. Para o primeiro detector, nenhuma das 12 caixas de reserva da validação nem as 7 do teste recebeu nome correto com IoU ≥ 0,5. Isso mede localização e identidade juntas.
- O classificador de recortes foi continuado até 30 épocas. No teste de desenvolvimento de 137 recortes, passou de 35/137 para 106/137 acertos top-1; no tabuleiro, de 8/22 para 14/22; na reserva, de 0/7 para 6/7. Essa melhora depende de recortes já localizados, rótulos revisados pelo assistente e apenas sete exemplos de reserva. Não demonstra reconhecimento ponta a ponta nem precisão ao vivo. Os relatórios locais são `yolo-baseline/baseline-eval.json` e `yolo-baseline/continuation-eval.json`; `training/evaluate_yolo_champions.py` reproduz a avaliação.
- A GTX 1060 de 3 GB foi usada pelos treinos CUDA, chegando a 91% de utilização durante o detector de banco adversário nesta rodada. A utilização oscila entre lotes e validação.

## Cenas adicionais revisadas

- Cartas de aprimoramento: 15 imagens de treino com 27 caixas, 7 de validação com 12 e 4 de teste com 6. O teste de uma transmissão separada deu mAP50 de 0,995 e mAP50-95 de 0,896. São somente quatro quadros do mesmo tipo de interface; o resultado não comprova generalização a patches, resoluções ou cartas distintas.
- Carrossel: classificador de cena treinado com fontes separadas. O primeiro modelo acertou 7/8 quadros de teste; uma continuação com mais negativos acertou 6/8, portanto não substitui o primeiro. Oito quadros próximos de uma só partida são insuficientes para promoção ao HUD.
- Banco adversário: 33 caixas candidatas de treino e 9 de validação, sem identidade de campeão. O detector terminou por parada antecipada após 13 épocas e obteve mAP50 de 0,000328 na validação. O resultado é uma falha do experimento; não será integrado. As caixas excluem o mascote reconhecível, mas várias unidades ambíguas ficaram sem rótulo. Precisamos de mais quadros e anotações completas antes de repetir esse treino.
- Os manifestos `training/reviewed_*_20261009.json` registram caixas/quadros conferidos visualmente pelo assistente. Os construtores `training/build_reviewed_yolo_scenes.py` e `training/build_reviewed_yolo_classification.py` exportam datasets separados por vídeo e preservam proveniência. Nenhuma previsão foi aceita automaticamente como rótulo.

## Próximo passo do experimento

Ampliar exemplos reais e confirmar identidades das classes raras nos vídeos novos. Revisar integralmente caixas do banco adversário e distinguir tabuleiro, reserva e mascote antes de outro treino. Avaliar a cadeia completa de localização mais classificação por partida e zona. Nenhum dos modelos desta rodada foi promovido ao software; os resultados atuais não sustentam essa decisão.
