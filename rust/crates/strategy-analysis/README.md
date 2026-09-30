# strategy-analysis

Fatos auditáveis para decisões estratégicas.

O crate não escolhe sozinho "ROLL" ou "LEVEL". Ele calcula dados verificáveis que alimentam o policy/decision engine.

Para um alvo:

- cópias próprias;
- cópias observadas nos adversários;
- cópias restantes do alvo;
- jogadores contestando;
- chance de encontrar ao gastar diferentes budgets;
- cópias esperadas;
- juros sacrificados;
- ouro restante.

Exemplo conceitual:

```text
X, custo 4, level 7
self: 4 cópias
Player 2: 3 cópias observadas
restantes do alvo: 3

10g → P(hit) ...
20g → P(hit) ...
30g → P(hit) ...
```

O parâmetro `tier_total_remaining` precisa vir de uma camada contábil validada. O módulo não inventa quantas unidades invisíveis saíram da pool.
