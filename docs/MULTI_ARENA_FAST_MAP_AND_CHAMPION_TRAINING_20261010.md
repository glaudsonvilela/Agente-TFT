# Mapa multi arena, latência e treino de campeões — 10/10/2026

Branch de trabalho: `tft-map-gtx-20261010`.

## Objetivo

Ler o TFT em 1080p com endereços persistentes para as 28 casas de cada lado e
os nove espaços de cada banco. O vídeo deve continuar fluido enquanto o Rust
rastreia barras rapidamente e a leitura completa atualiza HUD, itens e contexto.
Os nomes dos campeões só entram na partida depois de uma validação visual
independente; uma casa posicionada ainda não prova ocupação ou identidade.

## Camadas atuais

1. **Vídeo e rastreio rápido:** os quadros são exibidos continuamente e o
   trabalhador Rust retorna barras com IDs temporais. A leitura visual completa
   corre em outra trilha, hoje amostrada a cada segundo.
2. **Alinhamento do cenário:** três perfis locais (`cyber`, `red`, `pond`)
   verificam cores em pontos do terreno. Quando o VOD aplica zoom ou pan, o
   alinhador ORB procura o mesmo terreno e projeta as posições candidatas.
   Esse alinhamento nunca identifica campeão nem dono da arena.
3. **Endereços espaciais:** `A1` a `D7` e `R1` a `R9` existem separadamente para
   o jogador e para cada rival. As coordenadas aparecem somente quando o lado
   está visível e o cenário conhecido foi alinhado. No trecho `pond` atual,
   apenas o lado inferior está visível; o lado superior permanece sem posição.
4. **Leituras e decisão:** HUD, loja, itens, sinergias e adversários são
   observações com origem e estado de confiança. O motor de decisão Rust pode
   se abster; os endereços de casas não são enviados como identidade confirmada.

Arquivos principais: `apps/hud_mapper/hm/{arena_registration,spatial_calibration,spatial_map,board_hub_live,runtime_session,studio_bridge}.py`,
`configs/ui/{cyber,red,pond}-arena-reserves-v1.json`,
`configs/ui/arena-references/`, `tools/e1-native/src/main.rs` e
`ui/tauri-design/connected.js`.

## Teste local reproduzível

Foi usado o replay de 50 s
`/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/experiments/full-hud-readiness-20261010/replay-multi-arena-50s-1080.mp4`.
O registro está em
`/mnt/sherlock-ssd/AgenteTFT/diagnostics/ubuntu-integrated-20261010/local-data/AgenteTFT-HUD-HM4/sessions/hm4-20261010-173427-398228`.

- 1.104 quadros de origem, 46 leituras completas registradas e sessão encerrada
  sem erro. A prévia exibiu cerca de 20–22 FPS durante a execução. O valor de
  0 FPS após o fim do replay significa que a reprodução terminou.
- Nas amostras alinhadas houve 7 do cenário `cyber`, 13 do `red` e 24 do
  `pond`; duas amostras ficaram sem alinhamento. Onze alinhamentos exigiram
  correção de zoom/pan por pontos do terreno. Esses números medem *encontro de
  cenário*, não precisão de casas ou de nomes.
- A leitura completa teve mediana de 347 ms, p95 de 581 ms e máximo de 736 ms
  de processamento; o tempo até o resultado teve mediana de 363 ms. A trilha
  Rust de barras estava perto de 11 ms no fim do replay. O gargalo observado é
  a leitura completa, sobretudo a etapa que monta o instantâneo e compara
  candidatos de itens. `training/board_hub_snapshot.py` agora registra tempos
  das subetapas para a próxima medição.
- O painel mostrou HUD e candidatos de itens/loja, mas nenhum nome de campeão
  foi validado e nenhuma dica acionável foi emitida. O vínculo entre jogador e
  tabuleiro adversário continua não verificado.

Depois dessa medição, o alinhador passou a procurar pontos em 480×270 e
projetar o resultado de volta para 1920×1080. Em 11 quadros com zoom/pan,
o ensaio isolado encontrou os mesmos cenários; a mediana da busca caiu de
101,6 para 39,4 ms nesse ensaio. A redução ainda precisa de uma nova medição
de ponta a ponta no software para demonstrar ganho percebido pelo usuário.

Os perfis são **calibrações candidatas** dos três cenários do teste. Não foram
validados casa por casa em todos os mapas do TFT. O próximo teste deve comparar
os centros sobre a imagem do jogo antes de permitir uso estratégico.

## Treino completo dos 65 campeões na GTX

A GTX 1060 de 3 GB está disponível via CUDA. O reinício do conjunto de dados
exclui pesos anteriores do TFT e rótulos gerados por predição. A coleção
revisada contém 106 recortes candidatos, cobrindo 46 personagens. A auditoria
de poses novas registra 80 famílias provisórias para a meta de 325 (cinco para
cada um dos 65), com 245 ainda faltantes e 19 personagens sem pose validada.
Ainda não há conjunto elegível para o treino final dos 65. Repetir 40 ou 60
épocas nas mesmas imagens não cria novas perspectivas.

Ordem para concluir: capturar recortes nativos de VODs 1080p/4K de partidas
distintas; isolar um corpo por recorte; confirmar manualmente identidades
duvidosas; deduplicar poses e separar vídeos inteiros para avaliação; fechar
cinco poses distintas por personagem; só então materializar o conjunto novo e
treinar na GTX. Medir a precisão em partidas não vistas antes de ativar o peso
no software. O experimento anterior de 46 classes teve 2 acertos em apenas
4 recortes de dois vídeos não vistos: é uma amostra pequena e não demonstra
precisão geral.

Como ensaio de coleta, o rastreio das barras entre os segundos 600 e 608 de
um VOD 4K produziu 51 recortes candidatos a partir de oito unidades que o
usuário havia identificado. A folha
`/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/source-review-20261010/temporal-600-608-review.jpg`
mostra que a maioria repete a mesma perspectiva. Eles continuam com
`may_train: false` e **não** aumentam a contagem de cinco poses. A ferramenta
`training/render_track_review.py` expõe esse tipo de repetição antes de
promover qualquer recorte para treino.

Referências de auditoria: `/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/source-review-20261010/coverage-report.json`
e `/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/roster/unified-reviewed-candidates-20261010.json`.
