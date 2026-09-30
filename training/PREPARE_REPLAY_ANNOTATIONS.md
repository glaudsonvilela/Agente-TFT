# Prepare replay annotations

Extrai frames de uma gravação e cria um template de ground truth.

## Amostragem por intervalo

```bash
python -m training.prepare_replay_annotations match.mp4 \
  --output-dir training/annotations/match-001 \
  --every-seconds 30 \
  --max-frames 40
```

## Timestamps explícitos

```bash
python -m training.prepare_replay_annotations match.mp4 \
  --output-dir training/annotations/match-001 \
  --timestamps-ms 95000,123000,181500
```

Saída:

```text
training/annotations/match-001/
├── annotations.json
└── frames/
    ├── 0001_000095000ms.jpg
    └── ...
```

Depois, preencha apenas os campos que conseguir confirmar visualmente:

```json
{
  "timestamp_ms": 95000,
  "image": "frames/0001_000095000ms.jpg",
  "hp": 82,
  "gold": 50,
  "level": 7,
  "stage": "4-1",
  "shop": ["A", "B", "C", "D", "E"]
}
```

O script requer `ffmpeg` e, para amostragem por intervalo, `ffprobe`.
