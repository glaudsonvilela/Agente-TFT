# TFT_GOAT — upstream de treinamento

O **Agente-TFT** usa o TFT_GOAT apenas como laboratório offline de RL/self-play.

## Pin atual

- Repository: `MielPopsssssss/TFT_GOAT`
- Commit: `d5358e9402569f745bea81b61c5aed0500c57d66`
- Licença: MIT
- Set reportado pelo upstream neste pin: Set 17

A referência canônica está em `tft_goat.lock.json`.

## Instalação

```bash
bash scripts/bootstrap_tft_goat.sh
```

O clone vai para:

```text
training/upstream/TFT_GOAT/
```

e é ignorado pelo Git do Agente-TFT.

## Fronteira arquitetural

```text
TFT_GOAT
  ↓
treino / self-play / avaliação
  ↓
checkpoint / policy export
  ↓
adaptador Agente-TFT
  ↓
ONNX ou formato aprovado
  ↓
runtime
```

O runtime do Agente-TFT **não importa o TFT_GOAT** e não depende de PettingZoo/PyTorch para funcionar durante a inferência.

Antes de atualizar o commit pinado:

1. revisar LICENSE;
2. rodar testes do upstream;
3. avaliar mudanças no observation/action space;
4. comparar métricas contra o pin anterior;
5. atualizar o lock explicitamente.

Isso evita que `main` do upstream mude silenciosamente nosso laboratório.
