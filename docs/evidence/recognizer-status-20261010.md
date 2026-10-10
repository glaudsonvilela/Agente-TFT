# Reconhecedor TFT — estado em 10/10/2026

## O que foi verificado

- No replay de 20 segundos em 1080p, a janela apresentou 436 quadros em 20,57 s (aprox. 21,2 quadros/s). Os dois motores juntos atualizaram o reconhecimento 18 vezes; mediana de 1.058 ms por inferência. A reprodução fluida não significa identificação fluida: os nomes ainda erram e algumas caixas oscilam.
- Um novo treino com as mesmas 102 amostras confirmadas, em escala de 1080p, **não melhorou** o teste separado: o modelo anterior e o novo acertaram 3/4 recortes no top 1 e 4/4 no top 5, em dois VODs não usados no treino. O conjunto é pequeno demais para afirmar precisão geral. Os pesos novos não foram promovidos ao aplicativo.
- A distribuição de uma vaga da loja agora usa chance por custo no nível e cópias confirmadas visíveis. O número é condicional: cópias não vistas com outros jogadores continuam desconhecidas. Apenas uma unidade identificada e rastreada pode reduzir o estoque; palpite visual não pode.
- Nomes lidos nos cartões da loja ficam como ofertas observadas, sem virar automaticamente o nome do corpo no tabuleiro. Uma compra confirmada e seguida até o banco/tabuleiro poderá fixar essa identidade.
- A fusão de evidências tem a fórmula para uma compra nova: probabilidade de loja × verossimilhanças medidas em dados separados. Cor, forma e classificador vindos do mesmo recorte contam como um único grupo visual. No momento não há calibração suficiente para converter o palpite visual em probabilidade real. Estágio/nível não apagam um campeão comprado antes.
- A variação de contagem de sinergia entra como restrição forte apenas quando é comprovado que uma única unidade entrou no tabuleiro do mesmo jogador, sem outra troca de unidade ou equipamento. Ela elimina candidatos sem os traços que aumentaram; uma linha ausente no painel não conta como zero. A ligação automática desse evento ainda não está pronta.
- Ao repetir o replay com o RF-DETR para HUD e recortes de corpo ancorados nas barras de vida, houve 35–36 atualizações em 20 s, mediana de aproximadamente 300–304 ms (GTX para o classificador), contra 18 atualizações e 1.058 ms com corpos detectados pelo RF e classificador na CPU. Em quatro corpos revisados de vídeos separados, as caixas ancoradas localizaram 4/4; o RF encontrou 2/4. O classificador acertou 2/4 nomes nos recortes ancorados, portanto a identificação ainda não está resolvida.
- A tela antiga mostrava o top 1 de cada leitura e trocava de nome a cada oscilação. Agora uma trilha conserva o nome até outro vencer a maioria de cinco leituras; no mesmo replay, as mudanças caíram de 44 para 3 em 101 comparações. Isso é estabilidade de exibição, não aumento medido de acerto nem probabilidade calibrada.

## Próximo gargalo concreto

Ligar a leitura de loja, mudança de ouro e aparecimento no banco em uma trilha contínua; depois preservar o nome pela movimentação banco→tabuleiro. Validar isso com as transições Morgana/Malphite já revisadas manualmente e com novas partidas não vistas. Só depois usar cópias inimigas identificadas para refinar a conta da loja. Evitar mais treino repetindo as mesmas cenas até existir ganho em partidas separadas.

## Arquivos locais pendentes preservados

`training/materialize_champion_restart.py`, `training/prepare_champion_restart.py`, `training/train_champion_yolo_restart.py` e `weights/` já continham trabalho local fora deste estágio e ficam fora deste registro salvo. Vídeos, recortes, logs extensos e pesos experimentais permanecem somente no SSD.
