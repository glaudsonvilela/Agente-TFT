# Replay Labeler

Interface local no navegador para preencher o ground truth dos frames extraídos do replay.

## Rodar

```bash
python3 -m training.replay_labeler training/annotations/match-001
```

Abra:

```text
http://127.0.0.1:8765
```

## Campos

Preencha somente o que estiver visualmente confirmado:

- cena;
- HP;
- gold;
- level;
- XP;
- stage;
- 5 slots da shop;
- unidades do board;
- jogadores observados no lobby/scouting.

Campos vazios são omitidos do ground truth e não entram no denominador de accuracy.

## Segurança

- `source_video`, `timestamp_ms` e `image` não podem ser alterados pela UI;
- cada save passa pelo `Replay Intake Gate`;
- escrita é atômica;
- a versão anterior fica em `annotations.json.bak`;
- o servidor escuta somente em `127.0.0.1` por padrão;
- nenhuma imagem ou anotação é enviada para fora da máquina.

## Navegação

- botões Anterior/Próximo;
- setas esquerda/direita quando o foco não está em um campo;
- Ctrl+S salva.

Ao terminar, rode:

```bash
python3 -m training.replay_intake \
  --video telemetry/replays/match-001/TFT_MATCH_001.mp4 \
  --annotations training/annotations/match-001/annotations.json \
  --output training/annotations/match-001/intake-report.json
```
