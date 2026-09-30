# ocr-tesseract

Baseline OCR local para desenvolvimento/replay no Ubuntu.

O crate implementa `HudOcrEngine` usando o executável `tesseract`:

```text
GrayImage
   ↓
PGM em memória
   ↓ stdin
tesseract
   ↓ TSV stdout
text + confidence
   ↓
perception-hud
```

Configuração:

- `--psm 8` para campos numéricos;
- `--psm 7` para stage/round;
- whitelist de caracteres;
- confiança derivada do TSV do Tesseract.

## Papel no projeto

É um **baseline mensurável**, não uma decisão de arquitetura permanente.

Depois de termos dataset real, podemos comparar:

- Tesseract;
- ONNX especializado;
- detector/recognizer custom.

O melhor backend será escolhido por precisão, latência e uso de CPU.
