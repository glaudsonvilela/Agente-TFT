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


## HM4.2 — caminho rápido e L2 shadow

Estado validado no Windows CI antes deste pacote:

- HUD numérico (stage/gold/level/xp) executa em paralelo, preservando políticas/thresholds existentes.
- HP roda em processo independente e em paralelo ao caminho principal.
- Cache exato por bytes de ROI para HUD; cache exato dos pixels realmente consumidos por loja/controles.
- HM4 usa 2 Hz como cadência padrão dos leitores.
- Loja/controles têm cadência separada de 2 s; entre leituras, o último resultado é reapresentado com idade e provenance explícitas, sem ser marcado como fresco.
- O L2 espacial é somente shadow diagnóstico: não escreve GameState, não alimenta leitores, não é ground truth e não pode virar training label.
- summary.json e audit_hm4_session.py registram explicitamente o modo neural e as permissões bloqueadas.

Benchmark determinístico do runtime em GitHub Actions, 1920x1080 (run 37079664767):

- primeiro frame completo/fresco: 468.12 ms native; 474.34 ms wall;
- segundo frame byte-idêntico/cacheado: 0.57 ms native; 6.86 ms wall;
- frame alterado com HUD rápido e loja fora da cadência: 477.30 ms native; 483.38 ms wall;
- frame alterado com HUD + HP em paralelo: 503.28 ms wall;
- reapresentação da loja fora da cadência: aproximadamente 0.03 ms no benchmark.

Esses números são benchmark do runner CI, não promessa de latência do PC real. A comparação de campo deve ser feita numa nova captura natural usando o mesmo formato de relatório da sessão anterior.


## HM4.2 — selo final de regressão

Antes deste pacote final, o fast path também validou:

- comparação automática old-vs-new de auditorias HM4, preservando a sessão anterior como baseline;
- guard automático contra regressão da rota rápida dos leitores;
- nenhuma alteração de threshold, ground truth, treino ou promoção do L2;
- L2 permanece shadow diagnóstico somente.

Este commit existe apenas para executar o full package gate sobre o mesmo código já aprovado no fast path.


## HM4.3 — HP assíncrono e encerramento gracioso

O teste natural HM4.2 de 2026-10-02 confirmou queda relevante de latência do caminho de leitores (p50 ~6241 ms → ~2104 ms; p95 ~9108 ms → ~4930 ms), mas mostrou que o HP1 síncrono ainda bloqueava a publicação de cada ciclo: p50 próprio ~1074 ms e p95 ~2436 ms. O relatório agregado está em `docs/HM4_2_FIELD_TEST_20261002.md`.

HM4.3 mantém os leitores e thresholds congelados e muda apenas o agendamento/proveniência:

- HP1 passa a uma fila independente latest-only de 1 Hz.
- O HUD/loja não espera mais o OCR de HP para publicar seu próprio resultado.
- Um resultado de HP só pode acompanhar um frame se for causal (nunca de um frame futuro) e pertencer ao mesmo segmento geométrico.
- HP com mais de 2 s é `async_stale`: o último diagnóstico é preservado na proveniência, mas o valor numérico não é apresentado como atual.
- Métricas de HP (fila, source→result e tempo nativo) são reportadas separadamente.
- O caminho HM3 preserva o comportamento same-frame anterior.
- Clicar **ENCERRAR** agora é parada graciosa: se não houve erro, a sessão é selada como completa com `stopped_by_user=true`; erros e timeouts continuam parciais.

Não há mudança de threshold, ground truth, GameState, permissão de training label, promoção de perfil ou ativação silenciosa do L2.
