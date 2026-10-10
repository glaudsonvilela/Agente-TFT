# Reinício do treino visual YOLO — 10/10/2026

Estado verificável em `/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009`.

- Os pacotes e manifestos ativos do YOLO anterior foram retirados do fluxo local de trabalho. Nenhum peso ou rótulo anterior é entrada do novo treino.
- Fontes examinadas até agora: quadros originais de três vídeos locais, um em 3840×2160 e dois em 1920×1080, com SHA-256 registrado em cada manifesto. Os recortes originais e suas versões ampliadas 2× ficam lado a lado.
- O usuário identificou 44 imagens. Destas, 39 são candidatas para revisão de pose, cinco recortes de campeão ainda misturam unidades ou estão obstruídos e cinco imagens de passivas/efeitos foram excluídas. Nenhum recorte atual aguarda nome.
- Vinte identidades têm ao menos um candidato confirmado. Esses totais **não** significam cinco poses diferentes por campeão.
- No lote 27–33, o usuário corrigiu 29 e 31 para Hecarim e identificou 28 como Ezreal. Os pares 29/31 e 30/33 parecem a mesma pose no mesmo quadro; cada par conta no máximo como uma pose até a revisão final.
- A auditoria visual provisória agrupa os candidatos em famílias de pose. Até agora, o maior número provisório por campeão é três; nenhum chegou a cinco poses distintas.
- No segundo vídeo, o usuário identificou 34 Ornn, 36 Alistar, 37 Draven, 38 Shen, 40 Lux e 41 Akali. Excluiu 35 e 39 como passivas. O recorte 38 foi ajustado para reduzir a presença da unidade vizinha; os originais foram preservados.
- No terceiro vídeo, o usuário identificou 42 Camille, 43 Azuporã (`DA_Sentinel18`), 44 Taric, 45 Diana, 46 Elise, 47 Kennen, 48 LeBlanc e 49 Caitlyn. Os recortes 42 e 44 ficaram em espera por obstrução; 45 e 47 foram ajustados, preservando os originais.
- Frente/costas e banco/tabuleiro são perspectivas da mesma identidade. As cinco poses por campeão serão verificadas antes de montar o conjunto final; quadros quase idênticos não aumentam essa contagem.
- O rastreador de barras em `training/track_fresh_champion_crops.py` associou 11 recortes entre três quadros do vídeo. São apenas propostas de continuidade para revisão visual; nenhuma virou rótulo de treino.
- Treino novo e avaliação em partidas não vistas: **não iniciados**. Os manifestos e o resumo atual estão em `unlabeled-review/*/manifest.json` e `progress.json` dentro da pasta do reinício.

Próxima etapa: buscar outras perspectivas e campeões em partidas diferentes. Só depois de verificar cinco poses realmente distintas por identidade será montado o conjunto de treino. As sugestões visuais anteriores não foram usadas como rótulos.

## Experimento isolado com 46 identidades (10/10/2026)

O estado acima descreve o início do reinício. Depois dele, a revisão humana chegou a 106 recortes confirmados em 46 identidades. A pedido do usuário, foi treinado **um classificador experimental**, separado do modelo principal, para medir se esse material já melhorava a leitura. O experimento usa 102 recortes para treino e reserva quatro recortes de dois VODs não vistos. O YOLO de localização do HUD não foi restaurado nem promovido por esse experimento.

**Resultado: reprovado para identificação ao vivo.** Nos quatro recortes isolados de VODs não vistos, acertou duas identidades; a amostra é pequena e não estima a precisão geral. Na prévia completa, os nomes apareceram errados porque a proposta de caixa baseada na barra de vida frequentemente recorta outra região. Comparando essa proposta com 59 caixas de referência em 19 quadros 4K, apenas 25 atingiram IoU de 0,5; a mediana foi 0,464. Para o Hecarim 126, a melhor proposta teve IoU de 0,115. O classificador também confundiu esse Hecarim com Ornn no recorte correto. Assim, tanto a localização quanto a classificação precisam melhorar. A velocidade de reprodução não explica os erros de identidade.

O conjunto ainda está longe das cinco poses distintas por identidade: 21 das 46 têm somente um recorte de treino e 42 têm menos de cinco, sem descontar poses repetidas. A validação interna do treino espelha os próprios recortes de treino e **não** deve ser anunciada como acerto em partidas novas. As previsões não foram incorporadas como rótulos.

O relatório reproduzível está em `experiments/reviewed-46-20261010/preview-audit.json` na pasta do reinício. A prévia experimental exige a opção explícita `--show-rejected-model` e sinaliza os nomes como palpites de um modelo reprovado. Nenhum peso desse experimento foi integrado ao software principal. O próximo treino depende de recortes de qualidade, poses distintas e um teste de localização no mesmo conjunto reservado, antes de nova prévia com nomes.
