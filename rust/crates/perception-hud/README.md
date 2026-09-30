# perception-hud

Camada tipada entre regiões do HUD e o `StateFusion`.

## Pipeline

```text
RoiFrame
  ↓
image-preprocess
  ↓
HudOcrEngine
  ↓
RecognizedText + confidence
  ↓
domain parser
  ↓
HudObservationBatch
  ↓
TemporalConsensus
  ↓
GameState
```

O backend de OCR é um trait substituível. A camada não depende de Tesseract, ONNX ou qualquer provedor específico.

Responsabilidades:

- preparar a ROI para OCR;
- identificar qual campo do HUD está sendo interpretado;
- normalizar texto;
- validar domínio;
- rejeitar valores impossíveis;
- preservar confiança e timestamp;
- converter a leitura em `HudObservationBatch`.

Campos iniciais:

- stage/round;
- gold;
- HP;
- level;
- XP.

## Regra conservadora

O parser **não corrige automaticamente letras para números**.

```text
"50"  → válido
"5O"  → rejeitado
```

Se um recognizer quiser interpretar `O` como `0`, essa decisão precisa acontecer no modelo e vir acompanhada de confiança explícita. Heurísticas silenciosas não viram verdade no `GameState`.

## Pré-processamento

Por padrão:

- grayscale;
- contrast stretch;
- threshold binário;
- upscale 3×.

Esses parâmetros são configuráveis por campo e serão calibrados com fixtures reais do TFT.
