# Replay Intake Gate

Validação estrutural antes de executar a calibração real do Agente TFT.

O objetivo é detectar cedo erros que invalidariam o ground truth ou o alinhamento temporal entre vídeo, frames e telemetria.

## Uso recomendado

Depois de extrair os frames:

```bash
python -m training.prepare_replay_annotations match.mp4 \
  --output-dir training/annotations/match-001 \
  --every-seconds 30 \
  --max-frames 40
```

Preencha `annotations.json` e rode:

```bash
python -m training.replay_intake \
  --video match.mp4 \
  --annotations training/annotations/match-001/annotations.json \
  --output training/annotations/match-001/intake-report.json
```

Exit code:

- `0`: nenhum blocker estrutural;
- `2`: existe pelo menos um blocker.

## Blockers verificados

- schema incompatível;
- `source_video` ausente ou diferente do vídeo informado;
- timestamp inválido, negativo, duplicado ou fora da duração;
- imagem referenciada inexistente;
- loja diferente de 5 slots;
- unidade/ID com tipo inválido;
- lobby com IDs duplicados;
- level fora do domínio de segurança;
- stage fora do formato `N-N`;
- ausência total de ground truth;
- replay sem stream de vídeo válida;
- `ffprobe` indisponível quando o vídeo precisa ser validado.

## Warnings

Warnings não bloqueiam a calibração estruturalmente, mas indicam que a amostra pode ser fraca:

- menos de 20 frames;
- mais de 200 frames na primeira rodada;
- resolução inferior a 1280x720;
- frame sem nenhum campo de ground truth;
- ausência de labels de cena;
- cobertura incompleta dos tipos de cena estratégicos;
- `ffmpeg` ausente.

## Scene labels opcionais

Cada frame pode receber:

```json
{
  "scene": "planning_shop"
}
```

Valores aceitos:

- `planning_shop`
- `board_bench`
- `scouting_opponents`
- `augment`
- `transition`
- `combat`
- `other`

Essas labels não entram no cálculo de accuracy. Elas existem para verificar se a amostra cobre diferentes situações estratégicas.

## Ordem operacional

```text
gravação real
  -> prepare_replay_annotations
  -> preencher ground truth
  -> replay_intake
  -> replay pipeline / telemetria
  -> replay_calibration
  -> corrigir percepção
  -> congelar baseline
  -> weight-replay-diff
  -> promotion gate
```

## Regra

Não ajustar `OpportunityWeights` para compensar percepção ruim.

Primeiro validar captura, timestamp, ROI, OCR/detector e consensus. Só depois comparar pesos contra um baseline congelado.
