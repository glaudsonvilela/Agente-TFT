# opportunity-inspect

CLI de laboratório para testar o núcleo de decisão no Ubuntu.

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-opportunity-inspect -- \
  opportunity.json
```

O arquivo contém:

- `state`: `GameState`;
- `facts`: fatos produzidos pelos analisadores;
- `now_ms`;
- `meta` opcional, como snapshot MetaTFT;
- `config` opcional.

Saída:

```json
{
  "report": {
    "all": [],
    "shortlist": []
  },
  "decision": {}
}
```

Isso torna cada recomendação reproduzível fora da partida.
