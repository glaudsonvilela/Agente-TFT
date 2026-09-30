# lobby-analysis

Análise determinística do que foi **observado** no lobby.

Exemplo:

```text
X
├── Player 2: X 2★ → 3 cópias observadas
├── Player 3: X 1★ → 1 cópia observada
└── total adversários: 4
```

O módulo não tenta adivinhar unidades invisíveis nem inventa o conteúdo da pool.

Ele fornece dados para mensagens como:

> Player 2 e Player 3 têm 4 cópias observadas de X.

Cálculos disponíveis:

- cópias próprias em board + bench;
- cópias observadas por adversário;
- total observado;
- ranking das unidades mais contestadas;
- lista de jogadores contestando uma unidade.
