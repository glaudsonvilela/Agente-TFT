# capture-replay

Backend de replay/vídeo para desenvolvimento no Ubuntu.

Dependências de runtime:

- `ffprobe` para metadados;
- `ffmpeg` para decodificação.

O vídeo é convertido em frames RGBA e exposto pelo mesmo trait `CaptureSource` usado por todas as outras fontes.

Uso conceitual:

```rust
let mut source = ReplayVideoSource::open("partida.mp4", 10)?;
let frame = source.next_frame()?;
```

O timestamp é determinístico, derivado do índice do frame e do FPS de análise escolhido. Isso permite repetir exatamente a mesma sequência em testes de percepção e regressão.
