# Pacote principal de identidade dos campeões

Pasta principal no SSD: `/mnt/sherlock-ssd/AgenteTFT/champion-corpus`.

O pacote materializa recortes do conjunto misto corrigido e 47 recortes adicionais de revisão visual. Não usa previsões do próprio modelo como nomes. Os arquivos são cópias reais, com hash individual no `manifest.json`; não dependem de links simbólicos para os conjuntos anteriores.

| Seção | Imagens | Uso |
| --- | ---: | --- |
| `train` | 731 | Treino de 65 classes |
| `val` | 32 | Seleção de pesos durante treino |
| `test` | 127 | Comparação posterior, sem dez exemplos correlacionados de Xayah |
| `correlated_holdout` | 10 | Xayah da mesma origem que 22 imagens de treino; não usar como teste independente |
| `quarantine` | 3 | Identidades visualmente conflitantes; não usar como rótulo |

O classificador atualmente instalado não mudou durante a montagem. Sua referência inicial é **99/127 acertos top-1** nos recortes de teste, com rótulos de revisão assistida. O candidato treinado com o pacote alcançou **104/127**, mas manteve **16/22** nos recortes de tabuleiro, igual ao modelo ativo. Uma cena de outra partida ainda não tem nomes de unidades verificados independentemente. Por isso, o candidato **não foi instalado**. Essas medidas não são precisão em partidas ao vivo. O pacote registra a comparação em `evaluations/decision.json` e mantém uma cópia dos pesos instalados em `models/active/`.

Os vídeos brutos, modelos experimentais e conjuntos antigos permanecem como proveniência histórica; **só este pacote é o caminho principal para novos treinos de identidade**.

O comando `training/assemble_champion_corpus.py` reconstrói o pacote a partir dos conjuntos de origem, confere a quarentena e as contagens da extensão, impede duplicatas exatas e verifica o hash de cada cópia. Ele recusa sobrescrever uma pasta existente.

Trabalho ainda pendente e preservado fora deste pacote: `apps/hud_mapper/hm/board_hub_live.py`, `apps/hud_mapper/hm/runtime_session.py`, `apps/hud_mapper/hm/visual_tracks.py`, `apps/hud_mapper/tests/test_visual_tracks.py`, `training/replay_hud_diagnostics.py` e `ui/tauri-design/connected.js` pertencem ao diagnóstico visual em andamento.
