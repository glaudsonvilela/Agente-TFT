# Reinício do treino visual YOLO — 10/10/2026

Estado verificável em `/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009`.

- Os pacotes e manifestos ativos do YOLO anterior foram retirados do fluxo local de trabalho. Nenhum peso ou rótulo anterior é entrada do novo treino.
- Fontes examinadas até agora: quadros originais de dois vídeos locais, um em 3840×2160 e outro em 1920×1080, com SHA-256 registrado em cada manifesto. Os recortes originais e suas versões ampliadas 2× ficam lado a lado.
- O usuário identificou 36 imagens. Destas, 33 são candidatas para revisão de pose, três recortes de campeão ainda misturam unidades e cinco imagens de passivas/efeitos foram excluídas. Nenhum recorte atual aguarda nome.
- Dezesseis identidades têm ao menos um candidato confirmado: Akali, Alistar, Azir, Diana, Draven, Ezreal, Fiddlesticks, Hecarim, Karma, Kha'Zix, LeBlanc, Lux, Ornn, Rek'Sai, Sejuani e Shen. Esses totais **não** significam cinco poses diferentes por campeão.
- No lote 27–33, o usuário corrigiu 29 e 31 para Hecarim e identificou 28 como Ezreal. Os pares 29/31 e 30/33 parecem a mesma pose no mesmo quadro; cada par conta no máximo como uma pose até a revisão final.
- A auditoria visual provisória agrupa os candidatos em famílias de pose: Diana 3, Kha'Zix 3, Ornn 2, Azir 2, Karma 2, Rek'Sai 2 e uma família para cada um dos outros dez campeões. Esses números ainda precisam de validação final; nenhum campeão chegou a cinco poses distintas.
- No segundo vídeo, o usuário identificou 34 Ornn, 36 Alistar, 37 Draven, 38 Shen, 40 Lux e 41 Akali. Excluiu 35 e 39 como passivas. O recorte 38 foi ajustado para reduzir a presença da unidade vizinha; os originais foram preservados.
- Frente/costas e banco/tabuleiro são perspectivas da mesma identidade. As cinco poses por campeão serão verificadas antes de montar o conjunto final; quadros quase idênticos não aumentam essa contagem.
- O rastreador de barras em `training/track_fresh_champion_crops.py` associou 11 recortes entre três quadros do vídeo. São apenas propostas de continuidade para revisão visual; nenhuma virou rótulo de treino.
- Treino novo e avaliação em partidas não vistas: **não iniciados**. Os manifestos e o resumo atual estão em `unlabeled-review/*/manifest.json` e `progress.json` dentro da pasta do reinício.

Próxima etapa: buscar outras perspectivas e campeões em partidas diferentes. Só depois de verificar cinco poses realmente distintas por identidade será montado o conjunto de treino. As sugestões visuais anteriores não foram usadas como rótulos.
