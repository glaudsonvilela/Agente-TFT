# item-strength

Avaliador local e estrutural de oportunidades de equipar item.

Esta primeira versão mede apenas o que o modelo local conhece com segurança:

- o item existe no inventário observado;
- o alvo está no board;
- o alvo tem slot livre;
- diferença de BoardStrength antes/depois.

Ela **não inventa DPS, AP scaling ou efeito especial do item**.

O prior externo (por exemplo MetaTFT) continua separado em
`external_meta_prior`.

```text
MetaTFT: item é recomendado
        ↓
ItemOpportunityFact (meta prior)
        ↓
item-strength
        ↓
simula item no board
        ↓
BoardStrength before / after
        ↓
local structural strength_gain
        ↓
Opportunity Engine
```

A confiança estrutural é capada em 0.35 até validação contra resultados/simulador.
