# Retomada do treinamento do reconhecedor — estudo do otimizador

Checkpoint: 05/10/2026, PR #47, branch `work/neural-combat-stage-recovery`.

O treinamento visual parou depois da seleção do candidato
`transfer-vertical` e da criação do protocolo
`docs/evidence/recognizer-training-20261005/optimizer-study-protocol.json`.
O estado registrado antes desta retomada é
`latest_optimizer_experiment.status = default_parity_running`.

A mídia, os modelos privados e os recortes continuam no SSD Sherlock. Eles não
são copiados para o GitHub.

## O que o runner faz

`scripts/resume_recognizer_optimizer_study.py`:

1. confere o SHA-256 do manifesto supervisionado;
2. confere o SHA-256 do modelo `transfer-vertical` privado no SSD;
3. recupera a raiz comum das imagens revisadas;
4. localiza o encoder DINO pelo SHA-256 fixado no protocolo;
5. mantém:
   - encoder congelado;
   - `upper_88x80_v1`;
   - lote de embedding = 1;
   - `vertical_alignment_v1`;
   - 642 exemplos nomeados;
   - 31 negativos explícitos;
6. roda primeiro `optimizer-default-parity`;
7. exige paridade exata dos pesos/biases da cabeça e das previsões dos splits
   train/validation/test antes de aceitar o experimento;
8. roda somente depois os braços limitados:
   - L2 = `1e-4`, máximo 2.400 épocas;
   - L2 = `1e-5`, máximo 2.400 épocas;
9. escolhe por macro-revocação de validação e depois menor cross-entropy;
10. conserva o baseline se nenhum challenger melhorar;
11. congela a escolha **antes** de Minjo/KH;
12. não promove nada ao HUD.

O runner cria uma pasta nova no SSD e nunca remove ou sobrescreve uma execução
anterior.

## Execução no Ubuntu

Na máquina que possui o SSD:

```bash
cd /home/hobit/Agente-TFT
git fetch origin
git switch work/neural-combat-stage-recovery
git pull --ff-only

python3 scripts/resume_recognizer_optimizer_study.py
```

Saída esperada no fim:

```text
OPTIMIZER_STUDY_OK=true
OUTPUT_ROOT=...
SELECTION=.../optimizer-study-selection.json
SELECTED_ARM=...
SELECTED_VALIDATION=...
SELECTED_MACRO_RECALL=...
SELECTED_CROSS_ENTROPY=...
RUNTIME_APPROVED=false
```

O resultado fica, por padrão, em uma pasta nova como:

```text
/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005/
  optimizer-study-resume-AAAAMMDD-HHMMSS/
```

## Descoberta de caminhos

O runner tenta recuperar automaticamente:

- raiz das imagens revisadas;
- encoder ONNX pelo SHA-256;
- `libonnxruntime.so`.

Se algum deles estiver fora dos locais já usados pelo projeto:

```bash
python3 scripts/resume_recognizer_optimizer_study.py \
  --images "/caminho/raiz/das/imagens" \
  --encoder "/caminho/encoder.onnx" \
  --onnxruntime "/caminho/libonnxruntime.so"
```

Também são aceitas as variáveis:

- `AGENTE_TFT_IMAGES_ROOT`
- `AGENTE_TFT_ENCODER`
- `ONNXRUNTIME_LIB`

## Gate seguinte

Após a seleção congelada:

1. avaliar **somente** o candidato selecionado em Minjo/KH;
2. não usar Minjo/KH para reajustar hiperparâmetros;
3. incorporar novas imagens do SSD apenas depois de revisão e vínculo de
   identidade, sem transformar previsão do modelo em rótulo;
4. aumentar diversidade das 10 identidades ainda dependentes de uma única fonte;
5. resolver as nove formas Lux restantes;
6. medir rejeição de desconhecidos;
7. reservar uma fonte realmente independente para o holdout final.

Até esses gates passarem, `runtime_approved=false` permanece obrigatório.
