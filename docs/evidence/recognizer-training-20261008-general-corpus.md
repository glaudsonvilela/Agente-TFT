# Treino conjunto do reconhecedor — 08/10/2026

Objetivo: medir o efeito de acrescentar, **de uma vez**, todas as fontes locais
com rótulos automáticos já adjudicados. O classificador da base sempre aprende
todas as identidades em conjunto; o experimento anterior acrescentara apenas
uma identidade nova (Leona) de uma única jogada.

## Dados e método

- Base revisada: 841 recortes em treino/validação/teste conforme o manifesto
  congelado; DINO ONNX permanece congelado e a cabeça softmax é reajustada.
- Evidência adicional de treino: 20 recortes aceitos, de três gravações e quatro
  identidades (Camille, Dragão Ancião, Draven e Leona). Parte deles são quadros
  vizinhos da mesma jogada; o número de recortes **não** representa 20 partidas
  independentes.
- Seis dos 20 são rótulos prateados com peso máximo 0,35; os demais são ouro,
  com limite de 0,5 quando os dois professores visuais discordam.
- As imagens, o manifesto com caminhos privados, os modelos e os logs ficam em
  `/mnt/sherlock-ssd/AgenteTFT/diagnostics/general-recognizer-trial-20261008/`.
  O Git registra só este resumo.
- Os oito rótulos antigos de Dragão Ancião/Draven omitiram `partition`. Uma
  cópia privada recebeu `training_pool_unlabeled`, conferida com o relatório
  da coleta de origem; IDs e pixels não foram alterados. O validador Python
  agora exige o mesmo campo que o Rust já exigia.

## Resultado

| Modelo | Validação | Macro-revocação | Entropia cruzada | Teste histórico |
|---|---:|---:|---:|---:|
| Base | 21/32 | 0,6893939394 | 3,1966182142 | 79/127 |
| Treino conjunto | 21/32 | 0,6893939394 | 3,1945904568 | 79/127 |

A regra numérica registrada escolheu o candidato pela pequena queda da
entropia cruzada. **Isso não demonstra melhor reconhecimento geral.** Dos
quatro IDs novos, a validação contém três Camille e nenhum exemplo de Dragão
Ancião, Draven ou Leona. O teste histórico também não mudou em acertos totais.
Não houve promoção ao HUD (`runtime_approved=false`).

## Correção de direção

O próximo treino precisa aumentar a **variedade entre partidas e aparências**
de forma ampla, não acumular quadros da mesma jogada nem fazer um experimento
por campeão. A avaliação deve reservar gravações inteiras fora do treino e
relatar cobertura, acerto e confusões por identidade e por fonte. O encoder
visual continua congelado; treinar sua representação exige um experimento
separado com dados diversos e uma comparação independente. Ajustar só a cabeça
com mais quadros correlacionados não resolve esse ponto.
