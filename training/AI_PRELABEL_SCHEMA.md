# AI prelabel schema

A saída da IA é **somente sugestão**. Ela não é ground truth e nunca deve sobrescrever silenciosamente `annotations.json`.

## Formato

```json
{
  "schema_version": 1,
  "source_video": "TFT_MATCH_001.mp4",
  "frames": [
    {
      "timestamp_ms": 50000,
      "image": "frames/0002_000050000ms.jpg",
      "suggestions": {
        "scene": {"value": "planning_shop", "confidence": 0.98},
        "hp": {"value": 100, "confidence": 0.96},
        "gold": {"value": 14, "confidence": 0.83},
        "level": {"value": 4, "confidence": 0.94},
        "stage": {"value": "2-3", "confidence": 0.92},
        "shop": {
          "value": ["UnitA", "UnitB", null, "UnitD", "UnitE"],
          "confidence": 0.61
        }
      }
    }
  ]
}
```

Campos aceitos:

- `scene`
- `hp`
- `gold`
- `level`
- `xp`
- `stage`
- `shop`
- `board_unit_ids`
- `lobby_player_ids`

Valores de `scene`:

- `planning_shop`
- `board_bench`
- `scouting_opponents`
- `augment`
- `transition`
- `combat`
- `other`

## Regras para a IA

1. Não inventar valor invisível ou ilegível.
2. Omitir um campo quando não houver leitura confiável.
3. `confidence` representa confiança visual no campo específico, não confiança geral do frame.
4. Shop precisa conter exatamente 5 slots; usar `null` quando o slot estiver ilegível.
5. IDs/nomes de unidades ou jogadores devem ser omitidos quando houver dúvida séria.
6. Não inferir uma compra de oponente a partir de um único frame.
7. Não transformar prelabel em ground truth sem revisão humana.
