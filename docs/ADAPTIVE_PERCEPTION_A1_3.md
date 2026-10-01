# A1.3 — Promotion / Reject / Rollback Gate

Base: A1.2 shadow ROI/anchor candidate search.

## Objetivo

A1.3 transforma um candidato shadow persistente em uma decisão auditável:

```text
active + candidate
       ↓
janelas comparáveis
       ↓
promotion gate
       ├── hold
       ├── propose_promotion
       └── reject_candidate
                 ↓
          activation receipt
                 ↓
           rollback guard
       ├── hold
       └── propose_rollback
```

O gate NÃO escreve o perfil ativo. Ele produz propostas e recibos serializáveis.
A aplicação real de uma troca de perfil permanece fora desta entrega.

## Princípios

1. Health operacional não é accuracy.
2. Reduzir `unknown` sozinho não autoriza promoção.
3. O candidato precisa manter confidence e âncora sem regressões materiais.
4. Erros/conflitos não podem aumentar além das margens configuradas.
5. Por padrão, um active saudável não é trocado.
6. Promoção e rejeição exigem histerese em múltiplas janelas.
7. Toda proposta pode ser registrada na telemetria.
8. Após ativação, degradação persistente gera proposta de rollback.
9. Nenhuma decisão modifica GameState, OCR, rulesets ou OpportunityWeights.

## PromotionPolicy

Defaults conservadores:

```text
min_comparable_samples = 30
promote_after_good_windows = 5
reject_after_bad_windows = 3
require_active_degraded = true

candidate coverage >= 0.85
candidate confidence p50 >= 0.70
candidate anchor p50 >= 0.70
operational score gain >= 0.05

error regression <= 0.01
conflict regression <= 0.01
confidence p50 drop <= 0.03
anchor similarity drop <= 0.05
```

O operational score usa coverage, confidence e âncora. Continua sendo score de
ranking operacional, nunca probabilidade de acerto.

## Classes de janela

- **not ready**: amostras insuficientes ou warming-up;
- **neutral**: candidato não piora, mas não tem vantagem suficiente, ou active
  continua saudável;
- **good**: candidato passa os gates e tem ganho operacional suficiente;
- **bad**: candidato degradado/stale ou viola limites de regressão.

Not-ready e neutral não contam como derrotas do candidato.

## Histerese

`PromotionGate` acompanha um único candidate profile. Se o candidate id muda,
os contadores zeram.

Após a primeira decisão terminal (`propose_promotion` ou `reject_candidate`),
ela fica congelada até reset/troca de candidato. Isso evita múltiplas propostas
para a mesma transição.

## ActivationRecord

Somente uma decisão `propose_promotion` pode gerar um `ActivationRecord`.

Ele preserva:

- activation id;
- perfil anterior;
- perfil promovido;
- snapshot baseline do candidato;
- âncora baseline;
- decisão que originou a ativação.

O record não prova que uma escrita em disco ocorreu; ele é o contrato de auditoria
para o componente que fará a troca futuramente.

## RollbackGuard

Depois de uma ativação, o guard compara o perfil promovido contra o baseline
capturado na promoção.

Defaults:

```text
min_comparable_samples = 20
rollback_after_bad_windows = 3

coverage drop <= 0.15
unknown increase <= 0.15
error increase <= 0.02
conflict increase <= 0.02
confidence p50 drop <= 0.10
anchor similarity drop <= 0.10
```

Também exige o mesmo subsystem/field da ativação. Perfil incorreto ou janela fora
de ordem são rejeitados.

Rollback continua sendo `propose_rollback`, não uma mutação automática.

## Telemetria

`telemetry-core` recebe payloads próprios para:

- ROI search report;
- promotion decision;
- activation receipt;
- rollback decision.

Isso permite reconstruir por que um perfil foi sugerido, rejeitado ou revertido.

## Testes obrigatórios

- promoção apenas após múltiplas janelas boas;
- active saudável bloqueia troca desnecessária;
- redução de unknown com regressão de âncora é rejeitada;
- erros persistentes rejeitam candidato;
- warming-up/amostras insuficientes não contam como bad;
- mudança de candidate zera histerese;
- activation exige proposta de promoção;
- rollback exige degradação persistente;
- perfil pós-promoção saudável não gera rollback;
- janelas fora de ordem são rejeitadas;
- decisões/receipts serializam e desserializam.

## Limite do A1.3

A1.3 fecha a **fundação adaptativa**, mas ainda não implementa o Profile Registry
persistente que troca arquivos ativos. Antes de permitir escrita automática em
produção, o registry deverá ser atômico, versionado, com histórico e rollback.

Próxima funcionalidade: HP dinâmico via `player_list`, usando A1.1/A1.2/A1.3
desde o início.
