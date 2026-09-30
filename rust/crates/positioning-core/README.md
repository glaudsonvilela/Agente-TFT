# positioning-core

Converte orientação semântica em movimentos somente quando a geometria do
board foi explicitamente configurada.

Nada é hardcoded sobre qual row representa "frente".

Exemplo de configuração:

```text
rows = 4
cols = 7
front_rows = [0]
back_rows  = [3]
left_cols  = [0,1]
right_cols = [5,6]
center_cols = [3]
```

Hints suportados incluem:

- front/back row;
- left/right side;
- center;
- combinações front-left, back-right etc.

O engine:

- exige posição atual conhecida;
- evita célula ocupada;
- escolhe a célula válida mais próxima;
- não propõe movimento quando o hint já está satisfeito.

O módulo não calcula matchup gain. Ele apenas transforma um hint em ação
geométrica válida. O evaluator de matchup continua separado.
