# E1 — segunda revisão de compatibilidade e encerramento

A primeira compilação Rust passou em Linux e Windows (48 testes do worker).
A integração Linux passou; a Windows falhou porque FFmpeg 9.0.2 recusou a opção
`-vsync`. Substituição: `-fps_mode passthrough`, mantendo PTS sem impor taxa.
A suíte real de mídia permanece obrigatória; nenhum teste foi removido.

Mudanças ligadas: snapshots profundos dos eventos antes da escrita assíncrona;
confirmação headless separada de UI; IDs de tarefas substituídas; parada fora da
thread gráfica e fechamento idempotente; custo residual IPC declarado, não
tratado como tempo puro de serialização. FFmpeg/ffprobe reais são empacotados,
não shims apontando para diretórios do runner. O workflow também verifica a
execução de mídia pelo .exe empacotado, além de fixtures e aplicação gráfica.

20 testes Python locais passaram, incluindo FFmpeg real. Os testes de fila que
utilizam WorkerFixture são explicitamente doubles. Não houve compilação Rust,
execução ONNX ou Windows neste ambiente local; esses testes são exigidos no CI.
O estado final da compilação e dos testes deve ser consultado no PR #35. Não
antecipar aprovação. Leitores antigos, pesos e catálogos permanecem intactos.
