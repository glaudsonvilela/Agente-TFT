# roi-replay-inspect

Analisa um vídeo/replay usando um `RoiProfile` calibrado e imprime apenas regiões que mudaram.

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-roi-replay-inspect -- \
  partida.mp4 configs/roi/meu-perfil.json 10 6000
```

Saída em JSON Lines:

```json
{"frame_id":42,"timestamp_ms":4200,"changes":[{"roi":"shop","score":0.18}]}
```

Isso permite medir quanto trabalho real de percepção será necessário antes de integrar OCR/modelos.
