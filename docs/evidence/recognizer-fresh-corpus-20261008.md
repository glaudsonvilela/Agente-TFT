# Reinício do corpus visual de campeões — 2026-10-08

O estudo novo usa fontes diferentes das imagens e avaliações anteriores. O registro privado no SSD exclui 18 IDs de fontes já usadas. Recortes e rótulos antigos não entram neste estudo.

Os arquivos de vídeo e os metadados de integridade estão em `/mnt/sherlock-ssd/AgenteTFT/diagnostics/fresh-champion-corpus-20261008/`. Os três arquivos novos foram conferidos em 1920×1080, com SHA-256 registrado e tabuleiro visível. Uma janela inicial de outro VOD da Twitch foi descartada após revisão visual porque mostrava notas do patch, sem partida.

| Partição | Fonte | Quadros amostrados | Propostas de recorte |
| --- | --- | ---: | ---: |
| Treino | YouTube, partida nova | 329 | 1.843 |
| Treino | Twitch, trecho com partida | 120 | 838 |
| Avaliação | YouTube, partida independente | 120 | 321 |

Total: **3.002 propostas de recorte**. Elas são caixas localizadas sob barras de vida; ainda não são exemplos identificados. Há **zero rótulos de campeão verificados** e **zero poses distintas por campeão comprovadas**. Portanto, esses números não são taxa de acerto nem cobertura do elenco.

O primeiro coletor foi interrompido após 280 quadros. Uma segunda execução completou os 49 quadros restantes; a sequência de tempos de 0 a 1.640 segundos, em passos de 5 segundos, foi conferida sem lacunas. Os coletores de Twitch e do vídeo de avaliação terminaram normalmente.

Em 8 de outubro, foi executado um treino exploratório sem rótulos com 2.681 recortes de treino, 321 recortes de uma partida separada para avaliação, DINO INT8 e MobileNet congelados, e um projetor treinado por contraste entre duas versões de cada recorte. Foram 20 épocas: a perda do objetivo de treino foi de **1,6284** na primeira e **0,8080** na última. A recuperação da mesma imagem no vídeo separado foi de **98,4% antes e depois**. Esses 321 pares são versões alteradas da **mesma imagem**, não pares de um campeão visto em posições diferentes. Portanto, o resultado é **inconclusivo para reconhecimento de campeões**; não compara os 23 pares do experimento anterior mencionados pelo usuário e não mede acerto de identidade. O peso exploratório ficou apenas no SSD, sem entrar no HUD. Métricas e logs estão em `meta/training-report.json` e `meta/training.log` no diretório privado do corpus.

Próxima etapa do estudo: revisar identidades nas fontes novas, exigir **dez poses visuais distintas por campeão**, separar partidas inteiras entre treino e avaliação, treinar e comparar os dois encoders com rótulos verificados e medir erros por campeão e latência. Mudar apenas a célula do tabuleiro não conta como nova pose. Cada rótulo aceito precisa de `champion_id`, `pose_id`, `crop_pixel_sha256`, `source_id` e `reviewer_verified=true`; duplicatas do mesmo recorte não aumentam a cobertura. Nenhum peso antigo foi promovido para o estudo novo.

O monitor em `trainer/scripts/watch_champion_training.py` mostra esses contadores e o estado real do treino no terminal do Ubuntu. O treino exploratório não altera o contador de rótulos revisados.

Este estudo treina apenas a percepção visual. A IA jogadora precisa de trajetórias da partida com observação, ação executada e resultado posterior para aprender uma política de decisões. O autojogo existente em `training/simulator_lab/selfplay.py` usa um laboratório sintético; os 500 jogos registrados em `docs/evidence/hex-simulator-20261004/policy-progress-500.json` não validam uma política para o TFT atual. Uma fórmula fixa de conselho não deve ser tratada como política aprendida.

Os arquivos modificados do HUD que já estavam pendentes nesta branch não fazem parte deste registro e foram preservados.
