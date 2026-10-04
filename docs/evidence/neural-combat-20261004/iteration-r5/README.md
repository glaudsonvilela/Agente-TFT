# Iteração r5 — fontes, cobertura e treino

## Leitura dos resultados

- `rule-map.json`: inventário de cada entidade selada e das lacunas de 22 sistemas.
- `supplemental-rule-map.json`: índices suplementares, elegibilidade desconhecida e conflitos.
- `online-champion-attributes.json`: 65 páginas/70 fichas de atributos lidas online;
  fontes suplementares e conflitos preservados, sem sobrescrever o catálogo.
- `online-video-review.json`: URLs, minutos, fatos observados e limites da revisão online.
- `video-mechanics.json`: revisão de vídeos locais, Bloodthirster e tooltip de Azir.
- `twitch-*.json`: uma transição de posição revisada; identidade e itens ainda desconhecidos.
- `trait-field-audit.json`: nomes recuperados por hash; não comprova fórmulas.
- `training.json`, `model-schema.json`: treino e identidade do candidato r5.
- `planning-evaluation.json`, `paired-comparison.json`: avaliação com sementes reservadas.
- `coverage.json`: o subconjunto executável real.
- `validation.json`: comandos e resultados de verificação.

Arquivos originais, capturas e transcrições ficam privados no SSD. Os relatórios
preservam hashes. Nenhum vídeo novo foi integralmente assistido ou convertido
em partida completa rotulada. O treino de 5.000 combates usa o simulador parcial;
não é treino de 5.000 partidas ou imitação dos VODs.

## Resultado e limitações

22 habilidades candidatas; 7 com integração de mana/combate; 0 validadas em replay.
8 características candidatas completas, mais Executioner 2; 27 itens/componentes.
148 Wisps e 249 aprimoramentos indexados não têm handlers completos.

A validação do modelo alcançou 85,84% no laboratório, contra baseline 51,77%.
Planejamento: 8 melhores/92 iguais/0 piores contra manter formação em 100 cenários.
A mudança de conteúdo impede comparação direta da acurácia r4/r5. O coach Windows
continua sem promoção deste candidato; `runtime_promoted=false`.
