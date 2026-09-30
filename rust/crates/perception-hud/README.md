# perception-hud

Camada tipada entre qualquer OCR futuro e o `StateFusion`.

Responsabilidades:

- identificar qual campo do HUD está sendo interpretado;
- normalizar texto;
- validar domínio;
- rejeitar valores impossíveis;
- preservar confiança e timestamp;
- converter a leitura em `HudObservationBatch`.

Campos iniciais:

- stage/round;
- gold;
- HP;
- level;
- XP.

## Regra conservadora

O parser **não corrige automaticamente letras para números**.

Exemplo:

```text
"50"  → válido
"5O"  → rejeitado
```

A correção probabilística, quando existir, pertence ao modelo/OCR e deve vir acompanhada de confiança. Isso evita transformar heurísticas silenciosas em dados "certos".
