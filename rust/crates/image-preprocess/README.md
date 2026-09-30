# image-preprocess

Pré-processamento determinístico de regiões do HUD antes do OCR.

Pipeline inicial:

```text
RoiFrame
  ↓
luma/grayscale
  ↓
contrast stretch
  ↓
binary threshold
  ↓
nearest-neighbor upscale
  ↓
OCR backend
```

A implementação é pequena, sem OpenCV e sem dependências nativas. O objetivo é ter um baseline previsível para gold, HP, level, XP e round.

O backend de OCR permanece desacoplado e poderá ser:

- Tesseract como baseline offline;
- modelo ONNX especializado;
- outro recognizer treinado com fixtures reais.
