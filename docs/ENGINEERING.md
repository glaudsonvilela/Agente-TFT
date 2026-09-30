# Engenharia — Agente TFT

## Requisitos não funcionais

### Latência

O sistema deve ser dividido por frequência:

- captura: alta frequência;
- percepção: frequência adaptativa;
- cálculos determinísticos: disparados por evento;
- policy: somente quando o estado relevante muda;
- LLM/PydanticAI: somente para decisões/explicações que justifiquem o custo.

O LLM nunca bloqueia captura ou atualização de estado.

### Confiabilidade

Toda observação deve carregar:

- valor;
- confiança;
- origem;
- timestamp;
- versão do detector/modelo.

Recomendações críticas não devem depender exclusivamente de observações abaixo do threshold configurado.

### Auditabilidade

Cada decisão deve poder ser reconstruída:

```text
GameState
→ features
→ candidate actions
→ math outputs
→ policy outputs
→ recommendation
→ player action
→ next state
→ outcome
```

## State machine

Estados mínimos:

- IDLE
- MATCH_DETECTED
- PLANNING
- COMBAT
- AUGMENT_SELECTION
- CAROUSEL_OR_SPECIAL
- POST_COMBAT
- MATCH_ENDED

Os módulos devem reagir ao estado, evitando análise cara quando não é necessária.

## Backpressure

Captura de frames não deve criar fila infinita.

Regra:

- manter último frame válido por ROI;
- descartar frames ultrapassados;
- não enfileirar trabalho de visão que já ficou obsoleto;
- priorizar eventos de transição.

## IPC

Preferência inicial:

- processo Rust como state service;
- agente Python separado;
- IPC local via HTTP loopback ou Unix socket;
- schemas versionados.

O protocolo deve ser simples o suficiente para poder migrar depois sem reescrever a lógica.

## Persistência

SQLite local para:

- partidas;
- snapshots selecionados;
- eventos;
- recomendações;
- ações do jogador;
- resultados;
- versões de patch/modelos.

Arquivos grandes (frames/modelos) fora do banco; o banco guarda referências e hashes.

## Versionamento de conhecimento

Toda entrada deve conter no mínimo:

- source;
- patch;
- set;
- collected_at;
- expires_at quando aplicável;
- confidence;
- source_hash.

Dados de patch antigo devem ser marcados como stale, não silenciosamente reutilizados.

## Segurança operacional

- chaves somente via env/secret store;
- nenhuma chave em logs;
- nenhum token em datasets;
- timeouts obrigatórios em fontes externas;
- circuit breaker para fontes instáveis;
- modo offline funcional com último Knowledge Pack válido.

## Observabilidade

Métricas mínimas:

- capture_fps;
- vision_hz;
- state_update_ms;
- event_to_policy_ms;
- policy_inference_ms;
- agent_roundtrip_ms;
- end_to_end_recommendation_ms;
- unknown_field_rate;
- low_confidence_rate;
- recommendation_change_rate;
- RAM/CPU.

## Testes

### Unitários
- matemática de economia;
- odds;
- transformação de state;
- thresholds;
- patch guards.

### Golden tests
Frames e GameStates conhecidos com saída esperada.

### Replay tests
Uma partida gravada deve produzir sequência determinística de eventos para uma versão fixa dos modelos.

### Shadow evaluation
Comparar recomendação do agente com ação tomada, sem alterar o jogo.

### Regression
Cada bug corrigido adiciona fixture permanente.

## Definition of Done de uma feature

Uma feature só entra como pronta quando tiver:

1. contrato de entrada/saída;
2. teste;
3. métrica;
4. telemetria;
5. comportamento degradado;
6. documentação;
7. compatibilidade com perfis de execução.
