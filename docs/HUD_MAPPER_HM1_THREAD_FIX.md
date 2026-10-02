# HM1 — conflito de orçamento de threads reproduzido

A integração real chegou ao mapeamento, OCR, HP e selagem de pixels. No run
36964703760, job110705803367, o watchdog180s registrou travamento em
`torch/autograd/graph.py:_engine_run_backward`, chamado por `hm/train.py`.
Não era ausência de amostras nem falha de reconhecimento disfarçada como sucesso.

Reprodução local em processo separado: aquecer o pequeno modelo com uma thread;
configurar o treinador com duas threads mantendo `OMP_THREAD_LIMIT=1`; executar
backward com batch8. A combinação antiga atingiu o watchdog10s. Com uma thread,
oito passos reais terminaram em aproximadamente0,79s. São dados sintéticos de
regressão, não um benchmark do treino completo ou precisão TFT.

A correção HM1 mantém uma thread no treinador e registra essa política no
relatório. O limite OpenMP dos leitores continua intacto. O teste novo repete a
ordem de inicialização em processo separado com watchdog e exige alteração real
dos parâmetros. Não foi retirado teste, abaixado limiar ou ignorado treinamento.
ONNX já utiliza orçamento explícito; não atribuímos a ele esse bloqueio.

30 testes locais passaram, incluindo a nova regressão. A compilação e o fluxo
completo no Windows devem ser conferidos no novo CI; não foram executados no
ambiente local. O checkpoint anterior e a tentativa que falhou permanecem no Git.
