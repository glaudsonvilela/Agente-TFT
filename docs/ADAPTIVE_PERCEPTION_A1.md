# A1 — Adaptive Perception Foundation

## Objetivo

A1 transforma a percepção de um conjunto de leitores calibrados em uma camada
capaz de detectar degradação e, nas etapas seguintes, avaliar candidatos de
recalibração sem editar ROIs manualmente a cada atualização.

A1.1 entrega **saúde operacional + drift detector**. Ele NÃO localiza uma nova
ROI ainda, NÃO treina um modelo e NÃO promove perfis.

## Regra de segurança

Perception Health é diagnóstico operacional, não accuracy.

Ele pode afirmar:

- aumento de `unknown`;
- conflitos;
- erros;
- queda da distribuição de confidence;
- observação aceita antiga/stale;
- degradação em relação a um baseline operacional.

Ele não pode afirmar que uma leitura está correta sem uma referência independente.
Prelabels, previsões do próprio leitor e repetição temporal não viram ground truth.

## Stream

A unidade de acompanhamento é:

```text
subsystem + field + profile_id
```

Exemplos:

```text
hud / gold / active-v4
hud / gold / candidate-search-17
player_list / hp / candidate-2
```

Perfis diferentes nunca compartilham a mesma janela estatística. Isso prepara o
A1.3 para comparar active e candidate sem contaminar as métricas.

## Outcomes

Cada tentativa de percepção produz exatamente uma classe:

- `accepted { confidence }`;
- `unknown`;
- `conflict`;
- `error`.

`unknown`, conflito e erro permanecem separados. Uma falha de backend não pode
ser escondida como ausência de leitura.

## Janela e métricas

A janela móvel calcula:

- amostras;
- accepted / unknown / conflicts / errors;
- coverage;
- unknown/conflict/error rate;
- confidence p50/p95 somente sobre accepted;
- timestamp da última tentativa;
- timestamp da última accepted;
- staleness.

Os defaults são diagnósticos iniciais, não thresholds calibrados de TFT:

```text
window_capacity = 60
min_samples = 12
max_unknown_rate = 0.20
max_conflict_rate = 0.05
max_error_rate = 0.05
min_confidence_p50 = 0.70
max_staleness_ms = 5000
degrade_after_bad_windows = 3
recover_after_good_windows = 5
```

Nenhum desses números altera o OCR ou o GameState no A1.1.

## Baseline operacional

Um baseline opcional registra somente comportamento operacional anterior:
unknown/conflict/error rate e confidence p50.

A comparação só é usada quando o baseline possui amostras suficientes.
O baseline não contém accuracy e não pode ser construído tratando a própria
previsão como rótulo.

## Estados

```text
warming_up
healthy
degraded
stale
```

Histerese evita declarar drift por uma única falha. Staleness pode aparecer sem
inventar uma nova amostra: basta o relógio avançar além da última observação
aceita.

## Integração planejada

A1.1:
- crate `perception-health`;
- integração diagnóstica no `HudPipeline`;
- snapshot serializável na telemetria;
- nenhuma influência sobre state/strategy.

A1.2:
- busca limitada de ROI/âncoras;
- candidatos versionados;
- nenhuma promoção durante a busca.

A1.3:
- active × candidate em shadow;
- promotion/rejection/rollback auditáveis.

Depois disso, HP dinâmico via `player_list` será o primeiro leitor novo a usar
a fundação adaptativa desde o início.

## Gate A1.1

O gate de código exige:

1. uma falha isolada não degrada o stream;
2. falhas persistentes geram `degraded`;
3. recuperação exige histerese;
4. stale é explícito;
5. perfis são isolados;
6. amostras fora de ordem são rejeitadas;
7. snapshots fazem round-trip de serialização;
8. health não altera GameState nem pesos.

A1.1 não aprova auto-recalibração. Isso começa no A1.2.
