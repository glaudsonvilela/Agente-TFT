# A1.6 — executor diagnóstico ligado ao coordenador

Base: A1.5 (`8db33be4b6efd721f3cbd650c36ff0e688fca708`).

## Estado recebido

A execução A15 do usuário registrou três decisões `skip_already_evaluated`,
nenhuma intenção, diário na revisão 3 e registry A14 na revisão 1. O sinal foi
`visibility_unresolved` na primeira sequência e `healthy` nas outras duas.
A candidata `hp_text_fit_v1` continua em quarentena. Não fabricar trabalho,
liberar essa candidata ou refazer OCR para demonstrar o executor.

## O que passa a executar

O módulo `perception_worker.py` consome no máximo uma reserva A15 por chamada.
Ao contrário de A15, esta camada pode executar o binário Rust pareado, auditar o
resultado, importar evidência no A14 e finalizar a reserva no A15. Não seleciona
perfil de produção nem escreve GameState. O registro continua sem approve/clear.

Fluxo de uma reserva elegível:

```
produtor de observações -> submit_observations -> reserva A15
     -> journal de tentativa -> rechecagem do A14/fontes
     -> binário Rust preservado -> auditoria HP4 -> revisão A14 -> conclusão A15
```

`perception_work_source.submit_observations` é uma API interna: recebe manifest,
pixels e observações do produtor, verifica hashes e vincula o pacote à mesma
identidade do pedido A15. O coordenador recebe apenas status, timestamp, hash e
unicidade do marcador; não recebe valores esperados. O pacote não aceita comandos,
labels ou parâmetros para escolher um executável. A origem semântica das observações
continua sendo responsabilidade do produtor confiável; hash não autentica uma
previsão nem prova que ela veio de um sensor. Não há CLI para tratar um JSON
arbitrário de status como captura confiável.

O par nativo permitido nesta revisão é `hp1`/`hp_text_fit_v1`, identificado pelos
hashes registrados do binário e configuração. Não existe despacho genérico de
scripts/modelos. A candidata histórica bloqueada não recebe execução automática.
Novos tipos de leitor exigirão adaptador e registro explícitos, não renomeação.

## Limites e isolamento de trabalho

Reserva precisa existir, corresponder ao contexto/par/fontes, estar pendente e
ter no máximo 120 segundos de idade. Exige suporte `degraded` reconstruído dos
mesmos status reservados. Preserva orçamento/cooldown A15: não reserva novamente,
não reembolsa falhas e não substitui evidência ausente.

Até 128 imagens, 32 MiB por imagem e 512 MiB no conjunto, JSON até 16 MiB.
Configuração/executável e imagens são conferidos antes/depois. Cópias privadas de
binário/configuração são verificadas por hash antes do subprocesso. Report nativo
precisa passar `review_batch` HP4: escalas, sinais, comparação e temporalidade.
Mudança de status do baseline entre observação e execução invalida o resultado,
em vez de fingir que o agendamento foi feito sobre a nova observação.

A14 é consultado imediatamente antes e depois do subprocesso. Bloqueio novo não
é removido pela execução. Resultados válidos acrescentam avaliações/bloqueios;
nenhuma avaliação deste worker estabelece acurácia ou permite ativação.

## Concorrência, interrupção e persistência

Não migra schemas A14/A15 e não cria um terceiro banco. Usa journal por pedido:

```
telemetry/data/perception-registry/
  registry.sqlite3                  # A14
  coordinator.sqlite3               # A15
  coordinator.sqlite3.a16.lock       # lock POSIX do executor
  worker/sources/<request_id>.json
  worker/attempts/<request_id>/
    CLAIM.json
    manifest.json / source.json
    probe / profile.json
    events.jsonl / native.stderr / report.json / review.json
    FINAL.json
```

Diretório e claim persistem antes do spawn. O arquivo final completo é publicado
sem sobrescrita; um resultado final já selado pode finalizar A15 após reinício
sem repetir o cálculo. Uma tentativa sem resultado selado é marcada interrompida,
nunca relançada automaticamente. Não apagar journals para contornar deduplicação.
Erro/corrupção falha fechado; não há reset silencioso.

O supervisor limita execução a 120 segundos e arquivos a 32 MiB cada. Mantém pipe
aberto pelo pai: EOF, inclusive morte do pai, encerra o grupo do processo nativo.
O lock é herdado pelo supervisor até cleanup, para impedir outro worker de avançar
enquanto o subprocesso anterior termina. Testes de processo verificam o caminho
normal, erro, timeout com descendente e morte do pai.

Não há transação distribuída entre subprocesso, filesystem, A14 e A15. Um crash
pode desperdiçar cálculo; o desenho prefere falha conservadora a rerun implícito.
A14 usa importação idempotente e A15 usa confirmação idempotente. Um arquivo FINAL
é evidência de resultado verificado, não prova de resistência a toda falha física.
Local POSIX single-user; lock/hash/grupo de processos não são sandbox nem assinatura
contra código hostil com acesso ao computador. Descendentes que abandonem a sessão,
processos ininterruptíveis e filesystem sem flush/locking correto não têm garantia
universal de encerramento ou durabilidade.

## Comando no Ubuntu

```
bash scripts/work_match001_perception.sh
```

Com o estado A15 reportado, deve retornar `jobs_processed=0`, nenhuma chamada ao
binário/OCR e revisões 3/1 preservadas. Não recompila, não decodifica vídeo nem
ressuscita a candidata. Fila vazia é resultado correto. Cria relatório novo em
`telemetry/data/a16-worker.XXXXXXXX/report.json`, com `A16_SUMMARY` e `A16_REPORT`.

A chamada é explícita e finita, não um daemon. A fonte contínua de observações
não está ligada nesta entrega; existe handoff de arquivos/observações para o
produtor futuro. Também faltam geração/treino de modelos e ativação/reversão no
runtime. A1.6 entrega execução e feedback diagnóstico, não autoaprendizado completo
nem correção de 36/56. Não altera os leitores Rust, OCR, ROIs ou OpportunityWeights.

## Validação

Testes de controle usam backend simulado e verificam reserva, fontes, bloqueios,
recuperação e idempotência. Testes de supervisor usam processos reais. O HUD media
exige também o binário Rust, FFmpeg e Tesseract em integração positiva: PNGs
sintéticos com marcador e campo numérico vazio produzem observações reais;
reservar -> executar -> auditar -> registrar -> finalizar é percorrido. Espera-se
abstenção numérica, não um HP inventado. Não é medição de precisão do Match001.

A execução e números finais de testes estão registrados no PR. O ambiente desta
edição não tem Cargo; compilação/testes nativos são executados pelo CI.

Referências de implementação: documentação oficial Python `subprocess`, `fcntl`
e SQLite atomic commit. As garantias se limitam ao que os testes exercitam e às
condições de filesystem/execução descritas, não à ausência universal de falhas.
