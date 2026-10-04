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

## Valor neural de combate e comparação de ações

O laboratório de combate usa o catálogo selado e o pacote de regras da temporada.
O modelo representa cada hexágono dos dois tabuleiros com identidade do campeão,
estrelas e itens equipados. Duas cópias do mesmo campeão ocupam células distintas.
Tabuleiro, codificação e mecânicas permanecem separados dos atributos sazonais.

Para reproduzir o candidato, execute na raiz do repositório, em diretórios novos:

```bash
python -m training.compile_effects \
  --release knowledge/releases/TFTSet18/18.3/0674657d3f7c165d37045fbd45d8f7c56b20aef064660e6906c3985f0c8a0299 \
  --bindings configs/simulation/seasons/TFTSet18/18.3/manifest.json \
  --output datasets/combat-value/content.json

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m training.event_lab \
  --content datasets/combat-value/content.json \
  --output datasets/combat-value/run \
  --combats 3000 --epochs 120 --seconds 180

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m training.combat_choice_lab \
  --content datasets/combat-value/content.json \
  --model datasets/combat-value/run \
  --output datasets/combat-value/run/planning-evaluation.json \
  --cases 50 --planning --seed-offset 100000
```

- `training.event_lab`: gera confrontos, separa sementes antes de espelhar os
  exemplos, treina os pesos e registra cenários recusados por regras ausentes.
- `trainer.simulation.value_model`: codificação e inferência local; verifica
  hashes do modelo, conteúdo e código do simulador antes de carregar os pesos.
- `training.combat_planner`: compara manter, reposicionar ou equipar dentro de
  um orçamento. Todas as alternativas de uma rodada recebem a mesma semente;
  uma rodada interrompida é descartada. O prazo é verificado entre combates,
  portanto um combate em andamento pode ultrapassá-lo.
- `training.combat_choice_lab`: mede as escolhas em sementes diferentes das
  usadas para planejá-las. Registra inferência e tempo total de decisão.

O resultado por confronto é `+1` para vitória, `0` para empate/limite de tempo
e `-1` para derrota. Sua média não é uma taxa de vitórias. O melhor resultado
entre todas as alternativas é um limite diagnóstico, conhecido somente depois
da avaliação; ele não participa da escolha do agente.

### Limites de uso

O candidato cobre somente o subconjunto executável do simulador. Os pesos não
estão promovidos para o aplicativo. O experimento de equipamento pressupõe um
item completo disponível; ainda não mede o custo de guardar componentes.
Compra, rolagem, evolução, economia futura, aprimoramentos e partidas completas
precisam de regras e avaliações próprias.

Antes de habilitar dicas neurais, é necessário validar o estado observado
(campeões, estrelas, posições, itens e adversário), a cobertura das regras
envolvidas e o benefício das escolhas em partidas independentes. Acertar o
vencedor de combates simulados, isoladamente, não satisfaz esses requisitos.

Os relatórios desta revisão estão em `docs/evidence/neural-combat-20261004/`.
