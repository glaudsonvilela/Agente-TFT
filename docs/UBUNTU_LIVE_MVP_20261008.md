# MVP Ubuntu: replay na tela, motor HM4 completo

O vídeo continua em um reprodutor normal. O estúdio captura o monitor X11
selecionado e usa os mesmos leitores, catálogo, motor de decisões, HUB e
serviço de voz do aplicativo Windows. O backend de captura é o único caminho
alternativo: `ffmpeg x11grab` no Ubuntu, em vez do capturador Rust WGC.

## Abrir neste computador

Na raiz do repositório, execute:

```sh
python3 scripts/ubuntu_live_mvp.py
```

Abra o vídeo em um monitor, escolha esse mesmo monitor no estúdio e marque
"Estou assistindo um replay já encerrado". O estúdio mostra a prévia, a dica
e, no laboratório Ubuntu, os campos lidos e a razão de uma abstenção. O
reprodutor não entrega o arquivo ao Agente.

A sessão deve ser Ubuntu Xorg (`XDG_SESSION_TYPE=x11`). O ambiente Python
isolado fica em `/mnt/sherlock-ssd/AgenteTFT/diagnostics/ubuntu-live-mvp/.venv`.
Ele precisa de `onnx`, `onnxruntime`, `Pillow` e `numpy`; `ffmpeg`, `xrandr`,
`tesseract` e `ffplay` precisam estar disponíveis no sistema. O lançador usa
links locais no SSD para os leitores nativos, modelo, catálogo e interface.

## Ensaio observado em 8 de outubro de 2026

Fonte: vídeo de replay já autorizado, reproduzido em 1920×1080 no monitor
HDMI-1-1. Sessão:
`/mnt/sherlock-ssd/AgenteTFT/diagnostics/ubuntu-live-mvp/local-data/AgenteTFT-HUD-HM4/sessions/hm4-20261008-010358-980828`.

- 130 s de execução; encerramento completo, sem erro.
- 1.515 quadros recebidos; 122 leituras de HUD e 122 leituras do HUB.
- Prévia codificada em 1280×720, 12 FPS durante a execução.
- Estágio mudou de 2-6 para 3-1; ouro de 22 para 38; nível e XP foram lidos.
- O motor emitiu oito eventos de dica e a voz reproduziu três falas. O usuário
  confirmou que ouviu a primeira fala.
- Na etapa 2-6, o diagnóstico foi `NO_LEVEL_RULE_FOR_STAGE`; nessa janela o
  motor não ofereceu ação. Na etapa seguinte houve dicas de economia.
- Leitura de HUD p95: 317 ms; HUB p95: 414 ms. Esses valores são medidos até
  o resultado interno, não até o som sair do alto-falante.

O vídeo usado é de outro conjunto de TFT. Ele comprova a cadeia de captura,
leitura, dica e voz e mostra uma lacuna nas regras por estágio. Não valida os
nomes dos campeões, itens ou a qualidade estratégica para o patch atual.
Nenhum peso neural foi alterado por este ensaio.
