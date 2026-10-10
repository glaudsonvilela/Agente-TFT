# Perícia do caminho de aprendizado dos campeões — 09/10/2026

## Conclusão medida

O gargalo principal deste pacote não é a conversão da imagem nem a ordem dos nomes. A contagem de arquivos superestima as aparências distintas que o classificador viu, há rótulos contraditórios para pixels quase idênticos e o teste contém duas imagens quase iguais a imagens de treino. Treinar por mais tempo sobre os mesmos arquivos reforçaria uma aparência específica sem demonstrar reconhecimento de outras poses, arenas e estados do campeão.

| Etapa | Evidência | Implicação |
| --- | --- | --- |
| Entrada do software | Os 159 tensores de validação/teste produzidos por `hm.yolo_hud._tensor` foram **idênticos pixel a pixel** aos de `ultralytics.data.augment.classify_transforms(224)`. Os 65 nomes do ONNX ativo e do novo ONNX seguem a ordem do manifesto. | Não apareceu troca de índice, RGB ou normalização nessa etapa. |
| Expansão de treino | Dos **47** recortes de 128×144 adicionados, **46** reproduzem o centro de recortes antigos de 152×168 com erro médio RGB inferior a 5/255. **44** mantêm o mesmo nome; **2** trazem nomes diferentes para quase os mesmos pixels. | A expansão quase não acrescentou exemplos visuais novos e introduziu dois conflitos de supervisão. |
| Redundância mais ampla | Há **46 pares** quase idênticos entre os recortes antigos do próprio treino. Os 734 arquivos formam **655 componentes** segundo essa regra de cópia próxima; esse número ainda superestima partidas/aparências independentes. | Contar arquivos como exemplos independentes mascara repetição. |
| Kha'Zix | Os dois arquivos do treino são o **mesmo quadro** em dois cortes: remover 12 px de margem do JPEG antigo alinha ao PNG novo com erro médio **2,50/255** e correlação **0,992**. O novo modelo dá Kha'Zix com 0,957 nesse quadro, mas chama de Rengar o Kha'Zix de validação e de Hecarim o Kha'Zix confirmado numa partida reservada. | Para essa identidade, há uma só observação de treino efetiva. O modelo memoriza essa aparência e não a generaliza. |
| Aumento artificial | O treino ativo e o novo aplicaram corte aleatório de 50–100% da área, espelhamento em 50%, RandAugment e apagamento em 40%. Em 16 variantes da **mesma** imagem de Kha'Zix, o novo modelo acertou 15; isso não se traduziu na cena reservada. | Transformações de um único quadro não substituem ângulos, skins, arenas e fases reais diferentes. O efeito isolado de cada transformação ainda não foi medido. |
| Separação de teste | Dois recortes do teste, Camille e Cascalho, têm cópias quase exatas no treino; ambos foram acertados pelos dois pesos. Foram achados **três pares** porque Cascalho coincide com dois arquivos de treino. | A pontuação de 104/127 não é toda independente. Avaliar por partida de origem é necessário. |

Os conflitos de rótulo são `train/Azuporã/third-reviewed-0031.png` contra `train/Kog'Maw/frame-000074-marker-2.jpg` e `train/Diana/third-reviewed-0026.png` contra `train/Caitlyn/frame-000073-marker-7.jpg`. O teste de pixels não decide qual nome é correto; nenhum desses quatro arquivos deve servir como verdade de treino até revisão ou exclusão de ambos. As previsões dos modelos não serão usadas para arbitrar o conflito.

## Correção do processo

1. Separar partidas **antes** de produzir recortes. Uma partida inteira pertence a treino, validação ou teste. Detectar cópias por pixels, inclusive quando só a margem muda, e contar componentes e origens, não arquivos.
2. Retirar cópias redundantes e pares com rótulos contraditórios do próximo conjunto experimental, mantendo os originais e o modelo instalado intactos. Registrar por hash cada exclusão.
3. Para cada campeão escasso, coletar aparências realmente diferentes com identidade mostrada no próprio jogo ou confirmada pelo usuário. Acompanhar a unidade por vários quadros da mesma partida ajuda a obter poses, mas todos esses quadros continuam no **mesmo** grupo de origem.
4. Medir o classificador com partidas inteiras reservadas e nomes confirmados nelas. Só depois comparar regimes de transformação e duração do treino. O conjunto atual tem apenas dois nomes confirmados na avaliação de partidas reservadas; ele não mede a precisão geral.

Para o próximo piloto, usar **pelo menos cinco observações reais e distintas por campeão no treino**, de partidas ou fontes diferentes, incluindo tabuleiro e reserva quando possível. Quadros consecutivos, recortes da mesma imagem e transformações sintéticas não contam como novas observações. Separar outras partidas confirmadas para validação e teste; cinco imagens totais por classe não bastam para treino e avaliação independente. Reiniciar a seleção e a rotulagem do conjunto, mas comparar o treino com pesos visuais pré-treinados e uma nova cabeça de classificação antes de considerar pesos aleatórios. Esse piso de cinco mede viabilidade, não garante precisão nem dispensa aumentar as classes difíceis.

O comando [`training/audit_champion_learning_path.py`](../training/audit_champion_learning_path.py) reproduz a contagem de cópias e conflitos sem usar previsões como rótulos. [Relatório de pares](/mnt/sherlock-ssd/AgenteTFT/diagnostics/champion-image-forensics-20261009/learning-path-audit.json), [duas aparências de treino e a cena reservada](/mnt/sherlock-ssd/AgenteTFT/diagnostics/champion-image-forensics-20261009/khazix-training-coverage.png) e [transformações reais do treino](/mnt/sherlock-ssd/AgenteTFT/diagnostics/champion-image-forensics-20261009/kha-training-augmentation-grid.png) ficam no SSD. Nenhum peso foi substituído nesta perícia.

## Piloto de reinício concluído

O conjunto experimental selecionou 325 recortes, cinco por cada uma das 65 classes, após excluir 74 cópias próximas, quatro conflitos de rótulo, três cópias próximas da avaliação e quatro recortes visualmente inutilizáveis. O manifesto guarda origem e SHA-256. Nenhuma previsão do modelo foi usada como rótulo. O classificador partiu de pesos visuais genéricos `yolo26n-cls.pt`, não dos pesos anteriores de campeões. O treino parou na época 51 por ausência de melhora; a melhor época foi a 39.

| Medida | Candidato novo | Modelo em uso |
| --- | ---: | ---: |
| Validação disponível | 20/32 (62,5%) | Não repetida neste piloto |
| Teste disponível, top-1 | 92/127 (72,4%) | 99/127 (78,0%) |
| Teste disponível, top-5 | 114/127 (89,8%) | 116/127 (91,3%) |

Nos mesmos 127 recortes, o candidato corrigiu sete erros do modelo em uso e introduziu 14 novos; ambos erraram 21. **O candidato não foi promovido ao software.** Os rótulos desse teste foram revisados pelo assistente, sem verdade independente por partida. Portanto, estes números são evidência de desenvolvimento, não precisão em jogo ao vivo.

O limite principal continua sendo diversidade de origem: apenas **seis** classes têm as cinco capturas vindas de cinco fontes diferentes; Karma, Lux, Mamãe Bicuda e Morgana têm as cinco capturas de uma única fonte cada. Há cinco arquivos por classe, mas isso ainda não cumpre o plano de cinco observações independentes por campeão. O próximo ciclo deve ampliar partidas e poses das classes pouco diversas, confirmar rótulos nas cenas reservadas e então repetir a comparação. A fila visual, o conjunto experimental, os pesos candidatos, o log e as avaliações estão em `/mnt/sherlock-ssd/AgenteTFT/champion-restart-20261009/` no SSD; vídeos e pesos continuam fora do Git.

Arquivos de trabalho relacionados: `training/prepare_champion_restart.py`, `training/restart_visual_exclusions_20261009.json`, `training/materialize_champion_restart.py` e `training/train_champion_yolo_restart.py`. Outros arquivos pendentes no repositório: nenhum no momento deste registro.
