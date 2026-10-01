# AI-assisted replay prelabeling

Fluxo para acelerar a criação de ground truth sem transformar saída de IA em verdade automática.

## 1. Exportar lote

```bash
python3 -m training.export_ai_batch \
  training/annotations/match-001 \
  --output training/ai_batches/match-001-ai-batch.zip
```

O ZIP contém:

- `manifest.json`
- todos os frames extraídos

O manifest preserva `frame_index`, `timestamp_ms` e `image`.

## 2. Pré-anotar com IA

A IA deve devolver JSON no formato de `training/AI_PRELABEL_SCHEMA.md`.

Regras principais:

- omitir o que não conseguir ler;
- confidence por campo;
- não inferir compras de oponente a partir de um frame;
- não tratar sugestão como ground truth.

## 3. Importar sugestões

```bash
python3 -m training.import_ai_prelabels \
  training/annotations/match-001 \
  /caminho/prelabels.json
```

Isso grava apenas:

```text
training/annotations/match-001/prelabels.json
```

`annotations.json` permanece intacto.

## 4. Revisar no labeler

```bash
python3 -m training.replay_labeler training/annotations/match-001
```

O painel mostra:

- valor sugerido;
- confiança;
- botão **Aplicar sugestões visíveis**.

Somente depois da revisão e do save os campos viram ground truth.

## Primeiro uso neste projeto

Para `TFT_MATCH_001.mp4`, podemos exportar os 40 frames e enviar o ZIP para o ChatGPT. A pré-anotação visual em lote volta como `prelabels.json`, que entra no fluxo acima.
