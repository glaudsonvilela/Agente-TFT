# training/

Ambiente offline para treinar e avaliar a policy.

Fases planejadas:

1. baselines scripted;
2. imitation learning;
3. PPO;
4. self-play;
5. opponent pool com versões antigas;
6. avaliação reproduzível;
7. export ONNX.

O reward principal deve refletir colocação/resultado, evitando recompensas intermediárias que incentivem comportamento artificial.

A policy é avaliada por métricas objetivas antes de ser integrada ao coach.
