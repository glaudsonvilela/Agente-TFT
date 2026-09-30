# knowledge-core

Representação tipada do Knowledge Pack usada no hot path.

Atualmente carrega `units.json` e indexa:

- `api_name → UnitDefinition`;
- custo;
- nome;
- role;
- traits;
- unidades por cost tier.

O Opportunity Fact Builder usa esse catálogo para calcular compras, upgrades e pool conhecida sem consultar JSON bruto ou internet durante a partida.
