# synergy-core

Motor determinístico de traits/sinergias.

Ele responde fatos, não utility:

- quantas unidades únicas ativam cada trait;
- breakpoint atualmente ativo;
- próximo breakpoint;
- quais breakpoints seriam fechados ao adicionar uma unidade.

Duplicatas do mesmo champion não contam duas vezes por padrão.

Exemplo:

```text
Board:
Void = 3

Adicionar X:
Void = 4
closed breakpoint = 4
```

Esse fato pode ser consumido pelo board-strength evaluator e pelo Opportunity Engine, mas o synergy-core não inventa o valor de combate do breakpoint.
