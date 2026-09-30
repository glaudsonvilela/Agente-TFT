# perception-shop

Reconhecimento da loja com separação entre **score visual** e **confiança calibrada**.

```text
shop slot crop
    ↓
UnitClassifier
    ↓
unit_id + similarity + margin
    ↓
MatchCalibrator (parâmetros ajustados em dataset real)
    ↓
Confidence
    ↓
Observed<ShopSlot>
```

O classificador não pode promover uma unidade ao `GameState` sem calibrador.

## LogisticCalibration

Há suporte a regressão logística, mas o crate **não possui parâmetros padrão**. Os pesos precisam ser ajustados em dados rotulados e carregados de configuração.

Isso evita apresentar similaridade de template como se fosse probabilidade real.
