# Calibração de ROIs

O Agente TFT divide a tela em regiões de interesse (ROIs) para evitar processar o frame inteiro em todas as etapas.

## Regiões previstas

- `stage`
- `gold`
- `hp`
- `level_xp`
- `shop`
- `bench`
- `board`
- `items`
- `augments`
- `player_list`

As coordenadas são **normalizadas em [0,1]**, não absolutas em pixels. Isso permite reaproveitar o mesmo perfil entre resoluções compatíveis.

Cada ROI também possui:

- `change_threshold`: diferença mínima para disparar nova análise;
- `sample_step`: espaçamento das amostras usadas no detector de mudança.

## Regra importante

Nenhuma coordenada real será inventada no código.

Os perfis serão produzidos a partir de screenshots ou vídeos reais do TFT, validados visualmente e versionados com:

- resolução de referência;
- escala de UI;
- patch/set quando necessário;
- hash/versão do perfil.

## Fluxo

```text
Replay / frame
     ↓
ROI profile
     ↓
extract ROI
     ↓
change detector
     ↓
somente regiões alteradas
     ↓
perception
```

Isso reduz custo de CPU/GPU e evita chamar OCR/modelos quando nada relevante mudou.
