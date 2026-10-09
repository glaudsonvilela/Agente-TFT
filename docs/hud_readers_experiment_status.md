# Leitores do HUD: experimento de 9 de outubro de 2026

Os três treinos CUDA terminaram. Os pesos e conjuntos de imagens ficam no SSD de diagnóstico, fora do Git. Nenhum dos novos pesos foi conectado ao software ao vivo.

| Leitor | Dados de treino | Avaliação observada | Limite da medida |
| --- | ---: | ---: | --- |
| Campeões no tabuleiro e banco | 664 recortes, 65 classes | 107/137 acertos top-1 (78,1%); 92,0% top-5 | O teste cobre 47 classes; rótulos foram revisados pelo assistente, sem verificação humana independente. O modelo classifica recortes, mas não localiza unidades na tela. |
| Ícones de itens | 3.860 variações, 193 classes | 100% em 772 variações de validação | Treino e validação derivam do mesmo ícone oficial de cada classe. Isso mede memorização da arte, não reconhecimento de itens em partidas. |
| Algarismos do HUD | 554 recortes, 10 dígitos | 42/42 acertos no teste | Rótulos vêm de consenso do OCR, não de revisão humana. Há 7 recortes idênticos entre treino e teste, e o teste cobre 9 dígitos. O modelo lê um algarismo já recortado, não o valor inteiro na tela. |

O validador da biblioteca imprime `ERROR` quando um split não contém todas as classes de treino. Neste experimento, o processo continuou e alinhou as classes pelos nomes, mas a cobertura parcial torna a média insuficiente para afirmar que todas as classes foram dominadas.

**Estado:** o experimento de treinamento terminou; reconhecimento ao vivo de nomes, itens e valores completos ainda não foi demonstrado. Antes de integrar, avaliar em partidas novas com caixas e valores revisados por uma pessoa, medir a cadeia completa (localização, leitura e estabilidade temporal) e corrigir as classes que falharam. No teste separado de campeões, Karma teve 0/2 e Zyra 1/5 acertos; as classes com apenas uma amostra não permitem uma conclusão individual.
