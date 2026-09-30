# meta-hints

Converte `MetaSnapshot` em **hints e candidatos**, nunca em decisão final.

## UnitMetaHints

Expõe atributos como:

- recommended item IDs;
- top item IDs;
- positioning textual.

Esses hints precisam ser combinados com inventário real, board strength e matchup antes de virarem `OpportunityFacts`.

## CompTransitionCandidate

Uma comp externa só vira candidata quando há overlap real com board+bench.

Métricas:

- overlap ratio;
- unidades próprias já presentes;
- unidades faltantes;
- cópias contestadas observadas no lobby;
- prior estatístico descritivo;
- frequência/amostra.

Exemplo:

```text
Meta comp: A B C D
Board+bench: A B C X

overlap = 3/4
missing = D
opponents hold A1★ + D2★ = 4 copies observed

→ candidate generated
→ local pivot evaluator decides whether it is actually worth transitioning
```

Meta forte com overlap ruim não é candidato por padrão.
