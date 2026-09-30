# pivot-core

Avaliador estrutural de transições de comp.

Ele recebe uma comp candidata (por exemplo, MetaTFT) e constrói apenas um
board **alcançável com unidades já possuídas** em board + bench.

Nunca cria unidades faltantes.

Fluxo:

```text
Comp candidate
+ current board
+ bench
        ↓
reachable transition board
        ↓
BoardStrength before / after
        ↓
immediate structural gain
transition cost
missing units
replacements
        ↓
PivotOpportunityFact
```

O custo de transição combina:

- fração de unidades da comp ainda faltantes;
- fração do board atual que precisaria sair.

A confiança continua limitada pelo baseline de Board Strength.

Isso tira `PIVOT` do estado "meta-only", mas ainda não substitui Shadow/Swarm.
