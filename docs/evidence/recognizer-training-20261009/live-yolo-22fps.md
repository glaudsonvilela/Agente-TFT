# Leitura YOLO ao vivo no Ubuntu — 9 de outubro de 2026

Reprodução local do replay `replay-trecho-0845-1245.mp4`, com um único vídeo no estúdio e marcações do YOLO sobre os quadros. O modelo e o replay permanecem fora do repositório.

## Medição

- Prévia limitada a 22 FPS: em 20 amostras após o aquecimento, a mediana foi 22 FPS, com mínimo de 21 e máximo de 22. O contador visual chegou a mostrar 20 FPS em uma janela curta; portanto 22 FPS é o limite configurado, não uma garantia de cadência exata em todos os instantes.
- Leitura Rust do tabuleiro: mediana de 42 ms; percentil 95 de 82 ms.
- Observação visual: mediana de 440 ms; percentil 95 de 732 ms.
- Idade da leitura completa: mediana de 500 ms; percentil 95 de 775 ms.
- A tentativa de 30 FPS atingiu 30 em alguns momentos, mas oscilou até 19 FPS e aumentou a idade mediana das marcações para aproximadamente 2,7 s quando a prévia ficou sem controle de ritmo. O limite de 22 FPS manteve o vídeo e as leituras mais estáveis nesta máquina.

O OCR de texto das sinergias passou a funcionar em paralelo ao mapeamento Rust. Nenhum OCR de sinergia pode atrasar a resposta geométrica do quadro. O estúdio mostra candidatos de campeões no tabuleiro e no banco visível, além de unidades adversárias e mascotes, sem tratá-los como identidades confirmadas.

## Pendente

- Atribuir com evidência o banco visível ao jogador ou ao adversário durante a observação de outro tabuleiro.
- Treinar a identificação dos símbolos de sinergia no painel para enviar a observação visual ao motor Rust. O YOLO atual ainda não possui essas classes.
- Validar as identidades dos campeões e os itens em partidas independentes; as probabilidades exibidas ainda são candidatos não calibrados.
- Avaliar recomendações de jogo separadamente: o replay produziu dicas, mas esta medição não avaliou a pertinência estratégica delas.
- Não há arquivos de trabalho alheios ao reconhecedor pendentes neste checkout.
