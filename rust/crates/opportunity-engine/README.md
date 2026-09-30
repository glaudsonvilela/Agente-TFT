# opportunity-engine

Núcleo quantitativo do Agente TFT.

Antes de qualquer resposta, o motor recebe:

- `GameState`;
- fatos produzidos por módulos determinísticos/modelos especializados;
- contexto externo opcional e limitado;
- configuração de pesos.

Ele então:

1. enumera **todas** as oportunidades válidas;
2. calcula um vetor de características por ação;
3. calcula utility local;
4. mantém a lista completa para auditoria;
5. cria apenas um shortlist para avaliação profunda por policy/Shadow/Swarm.

## Vetor

```text
immediate_board_gain
upgrade_value
hp_preservation
economy_value
contest_urgency
flexibility
information_value
external_meta_prior
uncertainty
```

`utility` é score de ranking, **não probabilidade**.

## MetaTFT / fontes externas

O campo `external_meta_prior` é limitado por `MetaPriorPolicy` (default: ±0.10).

Portanto:

```text
meta forte + partida ruim
≠ recomendação automática
```

GameState, matemática real da pool, contestação e risco local continuam dominantes.

## Fases

- micro: buy/item/position;
- tactical: roll/level/hold;
- strategic: pivot/augment;
- information: scout.

O motor não inventa fatos ausentes. Um candidato só existe quando o módulo especializado fornece informação suficiente para avaliá-lo.
