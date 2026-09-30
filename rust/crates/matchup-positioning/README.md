# matchup-positioning

Avaliador estrutural de propostas de posicionamento contra um board adversário observado.

Ele **não modela targeting/combat como verdade**. O score é apenas um surrogate de exposição espacial:

- usa posições realmente observadas;
- orientação adversária é explicitamente configurada;
- ameaça estrutural usa estrelas + quantidade de itens, não DPS inventado;
- confiança é capada por padrão em 0.45;
- só promove movimentos que reduzem exposição acima do threshold.

Fluxo:

```text
PositionProposal
+
Opponent board observed
+
explicit perspective map
        ↓
structural exposure before/after
        ↓
normalized matchup gain
        ↓
PositionOpportunityFact
```

O resultado alimenta o Opportunity Engine como evidência adicional, não como probabilidade de vitória.
