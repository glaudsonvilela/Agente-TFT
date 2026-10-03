# HM4.4 — OCR Hub residente

## Motivo

O teste natural HM4.2 mostrou que, mesmo após cache/paralelismo, o caminho fresco ainda era caro. A inspeção do backend confirmou que cada chamada de OCR usa `Command::new(tesseract.exe)`: um novo processo por reconhecimento.

HM4.4 começa como laboratório isolado. Nenhum backend de produção foi trocado nesta etapa.

## Probe 1 — onde o tempo está

Windows CI, input sintético, 8 iterações:

- preprocessamento Rust: p50 **0.387 ms**, p95 **0.404 ms**
- adaptador atual `tesseract.exe`: p50 **107.957 ms**, p95 **114.998 ms**
- total: p50 **108.335 ms**, p95 **115.389 ms**
- fração do total atribuída ao recognize/process adapter: **99.65%**

Em uma execução anterior equivalente: preprocess p50 ~0.264 ms e process adapter p50 ~83.497 ms. A conclusão operacional é a mesma: preprocessamento não é o gargalo.

## Probe 2 — biblioteca residente

A distribuição Windows já inclui `libtesseract-5.dll`. Um laboratório Rust carrega essa DLL dinamicamente, inicializa uma única `TessBaseAPI` e reutiliza a instância.

Windows CI, input sintético, 10 iterações:

- inicialização residente única: **80.246 ms**
- CLI/processo atual: p50 **103.683 ms**, p95 **105.547 ms**
- C API residente: p50 **0.246 ms**, p95 **0.283 ms**
- speedup p50 do adaptador no microteste: **421.39×**

O input é sintético e produziu leitura vazia nos dois caminhos. Portanto estes números provam custo/latência do mecanismo de chamada, **não equivalência semântica, precisão TFT ou speedup final da partida**.

## Próximo gate antes de produção

Não ativar o residente ainda.

1. Implementar backend residente separado no crate OCR.
2. Preservar o backend CLI atual como referência/fallback.
3. Executar paridade CLI-vs-residente sobre imagens com texto e material natural revisado.
4. Exigir igualdade de texto/status/confiança dentro do contrato escolhido, ou registrar divergências sem promover.
5. Só então medir HUD numérico completo e loja.
6. Não alterar thresholds, perfis, ground truth, GameState, training labels ou L2.

Objetivo técnico: eliminar criação repetida de processos Tesseract sem misturar ganho de latência com mudança de política de leitura.
