# pattern-engine

Compara as três linhas de experiência:

1. ação recomendada;
2. ação humana observada;
3. ação do Shadow Player;

e também o melhor resultado encontrado pelo Counterfactual Swarm.

O motor acumula padrões por contexto configurado:

- stage;
- level;
- bucket de HP;
- bucket de gold;
- bucket de contestação;
- classe de ação recomendada.

Ele calcula apenas estatísticas observadas:

- taxa de concordância humano/agente;
- taxa de concordância shadow/agente;
- diferenças médias de reward;
- placement médio;
- frequência do padrão.

O módulo não transforma correlação em causalidade e não inventa reward ausente.
