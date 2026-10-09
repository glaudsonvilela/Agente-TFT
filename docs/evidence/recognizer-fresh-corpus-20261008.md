# Reinício do corpus visual de campeões — 2026-10-08

O estudo novo usa fontes diferentes das imagens e avaliações anteriores. O registro privado no SSD exclui 18 IDs de fontes já usadas. Recortes e rótulos antigos não entram neste estudo.

Os arquivos de vídeo e os metadados de integridade estão em `/mnt/sherlock-ssd/AgenteTFT/diagnostics/fresh-champion-corpus-20261008/`. Os três arquivos novos foram conferidos em 1920×1080, com SHA-256 registrado e tabuleiro visível. Uma janela inicial de outro VOD da Twitch foi descartada após revisão visual porque mostrava notas do patch, sem partida.

| Partição | Fonte | Quadros amostrados | Propostas de recorte |
| --- | --- | ---: | ---: |
| Treino | YouTube, partida nova | 329 | 1.843 |
| Treino | Twitch, trecho com partida | 120 | 838 |
| Avaliação | YouTube, partida independente | 120 | 321 |

Total: **3.002 propostas de recorte**. Elas são caixas localizadas sob barras de vida; ainda não são exemplos identificados. Há **zero rótulos de campeão verificados**, **zero posições distintas por campeão comprovadas** e **nenhum treino novo**. Portanto, esses números não são taxa de acerto nem cobertura do elenco.

O primeiro coletor foi interrompido após 280 quadros. Uma segunda execução completou os 49 quadros restantes; a sequência de tempos de 0 a 1.640 segundos, em passos de 5 segundos, foi conferida sem lacunas. Os coletores de Twitch e do vídeo de avaliação terminaram normalmente.

Próxima etapa do estudo: revisar identidades nas fontes novas, exigir dez posições reais por campeão, separar partidas inteiras entre treino e avaliação, treinar os dois encoders no mesmo conjunto verificado e medir erros por campeão e latência. Nenhum peso antigo foi promovido para o estudo novo.

O monitor em `trainer/scripts/watch_champion_training.py` mostra esses contadores e o estado real do treino no terminal do Ubuntu. Enquanto não houver rótulos revisados nem execução de treinamento, ele informa isso explicitamente.

Os arquivos modificados do HUD que já estavam pendentes nesta branch não fazem parte deste registro e foram preservados.
