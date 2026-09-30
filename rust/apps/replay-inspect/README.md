# replay-inspect

CLI de diagnóstico para vídeos/replays no Ubuntu.

```bash
cargo run --manifest-path rust/Cargo.toml \
  -p agente-tft-replay-inspect -- \
  partida.mp4 10 600
```

Argumentos:

1. arquivo de vídeo;
2. FPS de análise (default 5);
3. máximo de frames a ler (default 300).

Saída JSON com resolução, FPS do arquivo, FPS escolhido e timestamps processados.
