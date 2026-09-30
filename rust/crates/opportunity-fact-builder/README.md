# opportunity-fact-builder

Constrói automaticamente fatos do Opportunity Engine a partir de:

- `GameState`;
- `TftRuleSet`;
- `UnitCatalog`;
- lobby observado.

## Automático hoje

### Buy

Para cada slot reconhecido e comprável:

- custo;
- confiança;
- contestação;
- se uma compra fecha 2★ ou 3★.

### Roll

Para cada unidade já possuída em board/bench:

- próximo upgrade possível;
- cost tier;
- pool conhecida restante;
- cópias observadas fora;
- budgets configurados;
- probabilidade de hit;
- cópias esperadas;
- interest perdido;
- condição de parada.

A pool é explicitamente **known/observed pool**. O campo
`pool_accounting_confidence` existe porque benches/informação invisível podem estar ausentes.

### Level

Quando o ruleset do patch possui regras de XP:

- lê level, XP e gold observados;
- calcula o custo exato pelo `TftRuleSet`;
- considera níveis sequenciais configurados;
- só cria `LevelOpportunityFact` se o nível for alcançável agora;
- níveis não alcançáveis ficam em diagnóstico.

Se o ruleset não possui XP configurado, nenhum custo é inventado.

### Scout

Adversários stale/low-confidence geram oportunidades de scouting.

## Ainda especializados

- item: board/item analyzer + meta hints;
- positioning: matchup evaluator + meta hints;
- pivot: board transition evaluator + comp candidates;
- augment: augment evaluator.

Esses módulos podem ser mesclados como `extra_facts` no
`AutomaticOpportunityRuntime` antes do ranking final.

O builder prefere ausência explícita a fabricar um fato.
