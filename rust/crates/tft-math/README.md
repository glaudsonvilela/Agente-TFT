# tft-math

Matemática determinística do Agente TFT.

## Objetivo inicial

Responder quantitativamente perguntas como:

- quantas cópias do alvo ainda podem estar na pool;
- quanto a contestação observada reduz disponibilidade;
- qual a chance de ver pelo menos uma cópia em um shop;
- como essa chance muda com um orçamento de rolls;
- quanto de juros é perdido ao gastar agora.

## Sem números de patch hardcoded

O crate recebe como entrada:

- total de cópias da unidade;
- total restante da tier;
- odds da tier no nível atual;
- custo do roll;
- regras de economia.

Esses valores devem vir do Knowledge Pack/patch atual.

## Modelo de probabilidade

Para um shop:

1. número de slots da tier alvo é modelado pela probabilidade de tier;
2. dentro desses slots, as cópias são amostradas sem reposição da pool da tier;
3. a chance de zero hits usa distribuição hipergeométrica;
4. o resultado final integra todos os possíveis números de slots da tier.

Para vários shops, `estimate_roll_budget` assume snapshot de pool estável. Depois de comprar uma cópia, o caller deve recalcular com a pool atualizada.

Essa separação evita vender uma precisão falsa quando o estado mudou.
