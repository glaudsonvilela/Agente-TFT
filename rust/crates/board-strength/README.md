# board-strength

Baseline estrutural e auditável de força de board.

Ele **não** estima chance de vitória de combate. O score existe para comparar
duas configurações do mesmo estado antes de termos um modelo de combate
calibrado.

Componentes:

- material conhecido (cost + estrelas, com pesos explícitos);
- ocupação do board;
- densidade de itens equipados;
- breakpoints de traits ativos via `synergy-core`.

A confiança é deliberadamente limitada por `confidence_cap` (default 0.55)
até o baseline ser calibrado contra simulador/outcomes.

## Level planning

`best_bench_additions()` testa combinações limitadas do bench para estimar
qual board estrutural poderia entrar após ganhar slots.

Exemplo:

```text
lvl 7 board
+ subir lvl 8
+ colocar C

before = 0.58
after  = 0.66
gain   = 0.08
closed = Void 2
```

Esse `gain` pode alimentar `LevelOpportunityFact.expected_board_gain`.
Shadow/Swarm continuam responsáveis pela avaliação profunda.
