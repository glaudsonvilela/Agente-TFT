# telemetry/

Recorder e observabilidade.

Cada decisão deve gerar trilha suficiente para reproduzir:

```text
state → features → candidates → scores → recommendation → player action → outcome
```

Telemetria não deve conter secrets.

Dados brutos volumosos permanecem fora do Git.
