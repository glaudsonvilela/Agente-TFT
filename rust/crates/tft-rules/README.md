# tft-rules

Contrato runtime para regras que mudam por patch.

O objetivo é manter o código matemático estável e atualizar apenas os dados.

## Conteúdo

- patch;
- set;
- número de slots do shop;
- custo de roll;
- regras de juros;
- odds de custo por level;
- cópias por unidade em cada cost tier;
- provenance (`source`, `source_hash`).

## Fluxo

```text
Riot / CommunityDragon / fonte validada
                ↓
           normalizer
                ↓
       TftRuleSet JSON
                ↓
          validate()
                ↓
            runtime
                ↓
            tft-math
```

Não há valores reais de patch hardcoded neste crate. Os números usados nos testes são fixtures sintéticas e servem apenas para validar a matemática e o schema.
