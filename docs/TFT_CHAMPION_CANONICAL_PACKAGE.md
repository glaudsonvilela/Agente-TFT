# Pacote principal de identidade dos campeões

Pasta principal no SSD: `/mnt/sherlock-ssd/AgenteTFT/champion-corpus`.

O pacote materializa recortes do conjunto misto corrigido e 47 recortes adicionais de revisão visual. As correções de identidade dadas pelo usuário em 09/10 estão em `training/champion_label_corrections_20261009.json`; os palpites dos modelos serviram apenas para escolher imagens para revisão. Os arquivos são cópias reais, com hash individual no `manifest.json`; não dependem de links simbólicos para os conjuntos anteriores.

| Seção | Imagens | Uso |
| --- | ---: | --- |
| `train` | 734 | Treino de 65 classes |
| `val` | 32 | Seleção de pesos durante treino |
| `test` | 127 | Comparação posterior, sem dez exemplos correlacionados de Xayah; a imagem 12 foi confirmada como Sivir |
| `correlated_holdout` | 10 | Xayah da mesma origem que 22 imagens de treino; não usar como teste independente |
| `quarantine` | 0 | Os três conflitos antigos e a imagem 12 receberam identificação do usuário |

Os pesos instalados e o candidato histórico não foram alterados após a revisão do usuário. No conjunto corrigido, o modelo ativo acertou **99/127** recortes de teste e **26/32** de validação; o candidato histórico acertou **104/127** e **25/32**, respectivamente. O candidato histórico foi treinado com uma imagem de Azir sob Kha'Zix e segue **invalidado para promoção**; o peso ativo também herdou dois rótulos antigos que o usuário corrigiu. O pacote registra os resultados anteriores em `evaluations/` e mantém uma cópia dos pesos instalados em `models/active/`.

Um novo candidato foi treinado com os 734 recortes corrigidos. Acertou **104/127** no teste e **27/32** na validação, ante **99/127** e **26/32** do ativo. Nas 25 imagens escolhidas por suspeita de erro, acertou **8/25**, ante **5/25**; essa amostra inclui treino e não mede generalização. Em uma partida separada, o Kha'Zix confirmado ainda foi chamado de Hecarim. O candidato permanece fora do software. [Medição e decisão](TFT_TRAINING_EVIDENCE_MAP.md).

Os vídeos brutos, modelos experimentais e conjuntos antigos permanecem como proveniência histórica; **só este pacote é o caminho principal para novos treinos de identidade**.

O comando `training/assemble_champion_corpus.py` reconstrói o pacote a partir dos conjuntos de origem, aplica as 26 decisões de revisão pelo hash de cada imagem, confere a quarentena e as contagens da extensão, impede duplicatas exatas e verifica o hash de cada cópia. Ele recusa sobrescrever uma pasta existente.

Trabalho ainda pendente e preservado fora deste pacote: `apps/hud_mapper/hm/board_hub_live.py`, `apps/hud_mapper/hm/runtime_session.py`, `apps/hud_mapper/hm/visual_tracks.py`, `apps/hud_mapper/tests/test_visual_tracks.py`, `training/replay_hud_diagnostics.py` e `ui/tauri-design/connected.js` pertencem ao diagnóstico visual em andamento.
