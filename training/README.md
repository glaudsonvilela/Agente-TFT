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

Para gerar um candidato da revisão atual, execute na raiz do repositório, em
diretórios novos. Relatórios anteriores preservam os hashes da revisão usada;
mudanças no simulador exigem novo treino e nova avaliação:

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

## Caminho para o coach completo

Esta seção define trabalho necessário; os componentes abaixo ainda não estão
integrados como um treinador completo. A integração no software depende das
evidências de cada etapa, e não da quantidade de simulações executadas.

1. **Regras e versão:** selar atributos, habilidades, itens, características,
   aprimoramentos, fogos-fátuos, economia, rodadas e atualizações intermediárias.
   Identificadores ou descrições disponíveis não equivalem a efeitos executáveis.
2. **Fidelidade:** conferir alvos, trajetória, cadência, mana, dano, cura, escudos,
   efeitos simultâneos e liquidação de rodadas contra eventos de vídeos revisados.
   A tolerância de cada medida deve considerar a resolução e o FPS da fonte.
3. **Demonstrações:** converter os vídeos autorizados em sequências de estado
   observado, ação, próximo estado e resultado. Manter desconhecidos explícitos;
   uma explicação narrada não é prova de que a ação foi executada ou venceu.
4. **Aprendizado inicial:** treinar percepção e política com demonstrações
   revisadas. Separar partidas completas e duplicatas entre treino, validação
   e teste; manter rótulos humanos distintos de previsões dos modelos.
5. **Aprendizado por partidas:** treinar contra uma população de políticas,
   incluindo versões anteriores e estratégias diferentes. Avaliar colocação
   final e consequências de longo prazo, com aleatoriedade e informação oculta.
6. **Planejamento:** combinar política e valor com busca limitada de alternativas.
   Simular compras futuras por distribuição de probabilidades, sem oferecer à
   política o estado secreto ou o resultado futuro da própria avaliação.
7. **Liberação:** comparar com referências em partidas independentes e avaliar
   cada categoria de dica. Acurácia de combate, média global ou número de passos
   de treino não substituem essa avaliação. Medir atraso total e memória.
8. **Execução local e voz:** exportar uma versão compacta e identificada do modelo.
   A recomendação deve carregar ação, motivo, alternativa, confiança, instante
   observado e validade. A interface mostra o conjunto de dicas; a fala prioriza
   as úteis para a decisão atual e descarta orientações vencidas.

### Referências de método

- [AlphaZero](https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/alphazero-shedding-new-light-on-chess-shogi-and-go/alphazero_preprint.pdf):
  política e valor aprendidos por jogos contra si mesmo, com MCTS. Sua aplicação
  a TFT exige tratar sorte, vários jogadores e informação parcial.
- [AlphaStar](https://deepmind.google/blog/alphastar-grandmaster-level-in-starcraft-ii-using-multi-agent-reinforcement-learning/):
  demonstrações humanas seguidas de treino contra uma liga diversa. É uma
  referência para evitar que a política aprenda somente um estilo de adversário.
- [ReBeL](https://ai.meta.com/research/publications/combining-deep-reinforcement-learning-and-search-for-imperfect-information-games/):
  busca e aprendizado com informação imperfeita. A garantia publicada para dois
  jogadores e soma zero não se transfere automaticamente ao TFT de oito jogadores.
- [Sudoku, por Peter Norvig](https://www.norvig.com/sudoku.html): propagação de
  restrições e busca. A aplicação proposta aqui é eliminar ações impossíveis e
  verificar invariantes de ouro, inventário, ocupação e disponibilidade.
- [MuZero](https://deepmind.google/blog/muzero-mastering-go-chess-shogi-and-atari-without-rules/):
  aprende uma dinâmica útil ao planejamento a partir de experiência. Isso ainda
  exige transições e recompensas confiáveis; apenas transcrições são insuficientes.

### Cobertura de dicas exigida para a integração

O coach deve cobrir abertura, compra e venda, pares e melhorias, reserva de ouro,
juros, sequências de vitórias/derrotas, evolução, rolagem e limite de gasto,
transição de composição, disputas por campeões, força relativa, posicionamento,
adversários prováveis, itens e seu portador, decisão de guardar componentes,
aprimoramentos, fogos-fátuos, carrossel, escolhas de recompensas e revisão da
partida. Cada categoria precisa de casos positivos, de casos em que agir seria
ruim e de casos com leitura incompleta. A voz e a interface usam a mesma decisão.

O resumo de lacunas verificadas, fontes consultadas e revisão dos vídeos está em
`docs/evidence/neural-combat-20261004/readiness-audit.json`.
