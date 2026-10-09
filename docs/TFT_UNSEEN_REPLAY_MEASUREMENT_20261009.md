# Primeira medição em vídeos fora do conjunto de treino

Foram medidos **27 quadros de três vídeos de origem distinta**, nove por vídeo, em três trechos de cada um. Os IDs `-Xt_mZgsfp4`, `xl99CWEZG_w` e `v2893526719` não aparecem nas anotações antigas, na revisão recente de recortes nem no manifesto do pacote principal de identidade. Uma republicação da mesma partida em outro vídeo não pode ser descartada apenas pelo ID.

O ensaio usou o **classificador atualmente instalado**, o detector YOLO atual e o leitor nativo de barras do tabuleiro. Os nomes são previsões. O ensaio amostrou quadros de vídeo com `ffmpeg` e chamou o leitor em cada quadro; não mediu FPS contínuo nem incluiu OCR da loja ou inferência de itens. O inventário de itens ficou vazio neste teste, para isolar campeões.

| Vídeo | Quadros | Tempo mediano do leitor | Registros de tabuleiro | Reserva | Inimigos |
| --- | ---: | ---: | ---: | ---: | ---: |
| `-Xt_mZgsfp4` | 9 | 1.087 ms | 25 | 1 | 55 |
| `xl99CWEZG_w` | 9 | 868 ms | 53 | 7 | 14 |
| `v2893526719` | 9 | 969 ms | 32 | 21 | 28 |

No conjunto de 27 quadros, o tempo mediano foi **969 ms** e o percentil 95 foi **1.365 ms** por leitura isolada. A etapa YOLO ocupou 948 ms na mediana; o leitor nativo de barras, 80 ms. Essas medições incluem CPU e variam conforme o número de unidades; não são uma medida de desempenho durante reprodução contínua.

## Estabilidade dos nomes

Caixas próximas foram ligadas por posição em pares de quadros separados por até dois segundos. Após evitar a contagem dupla das unidades da reserva, houve **58 mudanças de nome em 117 pares aproximados**: 27/57 no tabuleiro, 2/18 na reserva e 29/42 nos inimigos. A associação espacial pode unir unidades diferentes durante movimento e combate; essa taxa mede instabilidade observável, **não precisão de identidade**.

No trecho de planejamento de `xl99CWEZG_w` aos 750–752 s, houve 1 mudança em 11 pares de tabuleiro e nenhuma em 4 pares da reserva. Já no trecho de combate de `-Xt_mZgsfp4` aos 1300–1302 s, houve 10/14 mudanças em caixas de tabuleiro e 12/13 em caixas inimigas. Isso orienta a próxima revisão para identidade durante combate e para separação de aliado/inimigo.

## Revisão visual inicial

Quatro quadros tiveram áreas inspecionadas manualmente a partir do vídeo **sem nomes de previsão sobrepostos**. A revisão marcou o centro visível de cada unidade; somente as áreas listadas entram na conta. É uma revisão visual do assistente, ainda não uma verdade de referência humana independente.

| Área inspecionada | Unidades localizadas | Caixas extras do leitor completo | Unidades não localizadas |
| --- | ---: | ---: | ---: |
| Tabuleiro aliado, um quadro | 5/5 | 1 | 0 |
| Reserva aliada, dois quadros | 9/9 | 1 | 0 |
| Campo inimigo, um quadro | 5/7 | 0 | 2 |

O leitor classificou como campeão um ponto de cenário junto ao tabuleiro em `xl99CWEZG_w` aos 750 s; o detector também enquadrou o mascote como unidade. Em `-Xt_mZgsfp4` aos 900 s, a reserva estava vazia, mas o leitor gerou um registro `Xayah` ali. Três identidades visuais evidentes de Alistar foram conferidas e as três receberam esse nome. **Três exemplos não permitem estimar acerto de nomes para os demais campeões.**

Os resultados brutos, os quadros sem sobreposição, a revisão e as caixas numeradas estão em `/mnt/sherlock-ssd/AgenteTFT/diagnostics/unseen-match-eval-20261009/`. `training/evaluate_unseen_replays.py` reproduz a amostragem e `training/score_unseen_replays.py` calcula a cobertura apenas de áreas revisadas. Nenhuma previsão foi incluída como rótulo no pacote de treino.

## Próximo conjunto de evidências

Revisar mais quadros de **cada** vídeo, com nomes comprováveis por tooltip ou outra referência visual, e separar planejamento, combate, reserva e inimigos. A avaliação de identidade por partida continua **indisponível** até existir essa referência; os pesos instalados continuam inalterados.
