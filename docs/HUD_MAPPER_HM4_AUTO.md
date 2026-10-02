# HUD Mapper HM4 Auto

HM4 mantém o motor de captura/leitura do HM3 e simplifica a experiência para o teste no Windows.

## Fluxo

1. Abra o HM4.
2. Clique em **Escolher monitor/janela** (ou **Detectar TFT**).
3. Selecione explicitamente a fonte.
4. Clique em **INICIAR**.
5. Acompanhe a captura, geometria, leituras e métricas.
6. Clique em **ENCERRAR** para selar a sessão.

Não há seleção manual de JSON/ONNX nem pasta de saída no fluxo HM4.

## Automação

- A resolução vem diretamente da fonte capturada.
- A pasta de sessão é criada automaticamente em `%LOCALAPPDATA%\AgenteTFT-HUD-HM4\sessions`.
- O HM4 procura um par válido `deployment-candidate.json` + `candidate-model.onnx` em locais padrão do aplicativo/usuário.
- Se encontrar um modelo L2/L3 compatível, ativa o observador neural automaticamente.
- Se não encontrar, o aplicativo **não bloqueia**: captura, telemetria, geometria registrada e leitores nativos continuam ativos. A parte neural fica explicitamente desativada.
- Os leitores Match001 continuam conservadores: em resolução diferente de 1920×1080 eles registram incompatibilidade em vez de inventar escala/OCR.

## Segurança do escopo

A captura continua sendo o processo Rust residente sobre Windows.Graphics.Capture/D3D11. HM4 não usa memória do jogo, injeção, automação de input, driver próprio ou bypass de anti-cheat.

## Entrega

O build Windows produz:

- `AgenteTFT-HUD-HM4-Auto-Windows-x64.zip`
- `AgenteTFT-HUD-HM4-Auto-Setup.exe`
- `HM4_PACKAGE_REPORT.json`

O pacote não inclui pesos pessoais, PyTorch, FFmpeg, replay ou treinador.


## HM4.1 — normalização conservadora dos leitores

HM4 pode derivar uma cópia temporária 1920×1080 para os leitores congelados quando a captura tem proporção 16:9. O frame capturado original continua sendo a evidência salva. A derivação usa RGB + Lanczos, registra tamanho de origem, tamanho canônico, fatores de escala e método, e projeta as caixas lidas de volta para as coordenadas do frame original.

Fontes que não são compatíveis com 16:9 continuam recusadas; não há stretching silencioso nem tentativa de adivinhar letterbox.

Contadores novos:
- `reader_normalized_runs`
- `reader_resolution_skipped`
- `reader_input_transform` em cada observação de ROI.

## Auditor de sessão

Para resumir uma sessão ou ZIP sem executar OCR/modelo:

```powershell
python scripts/audit_hm4_session.py "C:\caminho\teste.zip" --output hm4-session-audit.json
```

O relatório agrega resolução capturada, ativação neural, execuções nativas, normalizações, status por região, valores observados, campos stage/gold/level/xp/HP e quantidade de amostras ainda sem rótulo.
