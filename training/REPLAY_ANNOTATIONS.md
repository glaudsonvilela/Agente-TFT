# Replay annotations — ground truth

Formato mínimo para medir **accuracy real** do Agente TFT contra uma gravação.

Não é necessário anotar todos os frames. Uma primeira rodada útil pode ter
20–50 timestamps distribuídos entre planning, augment, scouting e combat.

## Schema

```json
{
  "schema_version": 1,
  "source_video": "partida-001.mp4",
  "frames": [
    {
      "timestamp_ms": 123450,
      "hp": 61,
      "gold": 48,
      "level": 7,
      "xp": 20,
      "stage": "4-2",
      "shop": [
        "TFT18_A",
        "TFT18_B",
        null,
        "TFT18_D",
        "TFT18_E"
      ],
      "board_unit_ids": [
        "TFT18_A",
        "TFT18_C",
        "TFT18_C",
        "TFT18_X"
      ],
      "lobby_player_ids": [
        "player-2",
        "player-3",
        "player-4"
      ]
    }
  ]
}
```

Campos são opcionais por frame. Se um campo não foi anotado, ele não entra no
denominador de accuracy.

## timestamp_ms

Tempo relativo ao início da gravação/stream de replay usado pelo pipeline.

O relatório procura o `StateSnapshot` mais próximo. O limite padrão é 250 ms:

```bash
python -m training.replay_calibration \
  telemetry/data/match.jsonl \
  --annotations training/annotations/match.json \
  --annotation-tolerance-ms 250 \
  --output telemetry/data/match-calibration.json
```

## Métricas

### HUD

Exact match por campo:

- hp;
- gold;
- level;
- xp;
- stage.

### Shop

`shop_slot_accuracy` compara cada posição anotada da loja.

`null` é permitido e significa que a anotação espera slot desconhecido/vazio.

### Board

O board usa multiset de `unit_id`, portanto duas cópias da mesma unidade contam
duas vezes.

Saídas:

- precision;
- recall;
- exact rate.

### Lobby

Compara o conjunto de `player_id` anotados/observados:

- precision;
- recall;
- exact rate.

## Regra

**Coverage não é accuracy.**

Uma leitura pode existir e estar errada. Por isso nenhuma métrica de coverage é
usada como substituta de ground truth.
