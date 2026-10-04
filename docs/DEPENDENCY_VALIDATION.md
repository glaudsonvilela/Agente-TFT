# Validação de combate, loja e progressão — 04/10/2026

## Implementação posterior à validação

As correções abaixo acrescentam regras executáveis ao simulador. Os valores, IDs e fontes ficam no pacote `configs/simulation/seasons/TFTSet18/18.3/`; os algoritmos genéricos ficam em `trainer/simulation/`.

### Combate

| Regra acrescentada | Comportamento testado |
|---|---|
| Monólito | Armadura/RM por inimigo vivo mirando na unidade; muda ao trocar de alvo ou morrer. Fórmulas de habilidades também consultam esses atributos dinâmicos. |
| Caçador | Cronômetro do alvo preservado durante atordoamento; reiniciado na troca de alvo. Amplificação só após o prazo. AD dos níveis 4/5 corrigido pelas notas 18.3. |
| Devastador | Vampirismo e dano adicional; verifica a vida de cada destinatário antes do impacto, com bônus dobrado estritamente abaixo de 50%. |
| Emanador | Regeneração de mana por nível; o bônus dos membros substitui o da equipe. Totais 3/4/6/8 extraídos das notas oficiais corrigem 2/3/5/8 do catálogo. |
| Inferno 2 | Ferimento e queimadura por segundo; renova a duração sem empilhar entre membros, mas permite outro grupo de queimadura. |

Cobertura candidata de características: **8 → 12 completas no pacote**, e **23 → 36 níveis executáveis de 91**. Executioner e Inferno continuam parciais. “Candidata” significa implementação com testes, não validação contra replay. Inferno 3/5/7 continua bloqueado porque modifica a loja; não foi reduzido artificialmente ao efeito de combate de Inferno 2. Cadência e atribuição de queimaduras ainda exigem calibração de replay.

### Loja e progressão

- O compilador agora entrega chances da loja dos níveis 1–10, custos de XP/rolagem, curva de XP e quantidades do pool. Os dados permitem testar a loja comum com campeões reais, incluindo compra e venda de unidades de uma estrela.
- `new_planning_probe()` constrói um estado explicitamente limitado à loja comum. Contabiliza peças possuídas, equivalentes das estrelas e ofertas reservadas de todos os jogadores antes de permitir ações.
- Formas compartilham uma identidade de estoque. A associação candidata das variantes de Lux evita criar dez estoques independentes; sua distribuição/seleção e fusão entre formas ainda não estão implementadas. Comprar Lux sem selecionar a forma é recusado.
- Compra, fusão, venda, nova loja e eliminação preservam o total de cópias. Um registro de totais detecta criação ou perda indevida de peças. Unidades de quatro estrelas exigem proveniência específica e não devolvem automaticamente 27 cópias.
- XP comprado e natural usam a mesma função, com validação de custos e limiares antes da alteração. Curvas inválidas não podem conceder ouro nem entrar em um ciclo infinito.
- A curva candidata usa **56 XP de 7 para 8**, conforme a fonte primária, e 68 para os níveis seguintes após o hotfix. A tabela secundária de 60 permanece registrada como divergência; a calibração visual atual continua pendente. [Notas oficiais 18.2](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-2/).
- Dependências globais ausentes são propagadas ao planejador; não viram uma lista vazia que possa ser confundida com uma recomendação válida de “manter”. A saída da busca identifica o escopo limitado e as dependências pendentes.

### Resultado e limites atuais

Os [testes e hashes desta implementação](evidence/dependency-fixes-20261004/validation.json) e a [nova auditoria compilada](evidence/dependency-fixes-20261004/compiled-audit.json) substituem os números de implementação abaixo; o relatório anterior fica preservado como histórico.

**As 12 composições completas ainda estão bloqueadas.** O núcleo Ravager agora ultrapassa suas características e para na habilidade de Akali; o núcleo Sivir ultrapassa Monólito e para em Blackthorn. Continuam faltando habilidades, integração de funções de mana, Wisps, lojas especiais, persistência sazonal, calendário/loot e aprimoramentos. Somente uma estrela tem preço de venda vinculado; capacidade do inventário ainda é hipótese de laboratório. O pacote continua em 18.3, com memória estratégica de 18.3B.

O estado de teste da loja comum não pode avançar pelo ciclo de partida completa. Nenhum treino novo de candidato ou promoção ao HUD foi realizado. Checkpoints anteriores têm identidade de motor diferente e precisam de novo treino/avaliação; não são reclassificados como válidos para estas regras.

Reprodução:

```bash
PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m unittest training.tests.test_dependency_implementations

PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m training.simulator_lab.dependency_audit \
  --output docs/evidence/dependency-fixes-20261004/compiled-audit.json
```

## Histórico — validação anterior (`fcca246`)

**A base corrigida passou nos testes. As 12 estratégias ainda não passaram na validação de dependências do patch.**

Foram executados 550 testes da suíte de treinamento, com resultado OK e 12 ignorados. O conjunto focado de combate, loja e rodadas teve 42 testes passando. Oito testes novos reproduziram falhas antes das correções: sete falhas contando subcasos e um erro. Esses números medem contratos do software, não fidelidade integral ao TFT.

### Correções realizadas

- Motor antigo: aprimoramentos não suportados agora causam recusa explícita. O motor por eventos continua aplicando os efeitos suportados.
- Planejamento: não permite rolar/comprar usando um aprimoramento desconhecido ou com efeito de planejamento sem implementação.
- Rodadas: estado explícito impede abrir duas vezes a mesma rodada para obter lojas gratuitas, ou resolver novamente uma rodada já liquidada para repetir renda/XP/recompensas.
- Loja: probabilidades negativas, não finitas e booleanas são recusadas. Oferta com campeão inexistente não cria uma identidade inválida no pool.
- Regressões verificam loja travada, conservação de cópias, ações atômicas e persistência dos ganhos implementados de combate.

O ciclo continua sendo de laboratório: não implementa automaticamente o calendário sazonal, carrossel, PvE, loot, pareamento ou efeitos pendentes. A recusa de uma mecânica não equivale à sua implementação.

## Evidência online revisada

### YouTube

[TFTAcademy / Wasianiverson — Como Executar um Rolldown](https://www.youtube.com/watch?v=qNOZMvMGcVo): transcrição automática lida integralmente e demonstração visual consultada em trechos próximos de 9:20–10:32.

A preparação, o espaço no banco, os upgrades e o tempo restante influenciam quando parar de rolar. O guia também distingue equipar durante o combate de ativar efeitos que exigem o início da luta. Isso revela uma lacuna adicional: o simulador atual só aceita ações no planejamento; não reproduz equipamento dinâmico durante o combate nem sua ordem de gatilhos. A tradução automática de uma passagem pode sugerir duas compras de Wisp; não foi usada para alterar o limite de compras.

O patch exato da gravação não foi estabelecido. O guia não foi convertido em rótulos de vitória ou em regras numéricas universais.

### Twitch

[Dishsoap — Blossom Cup](https://www.twitch.tv/videos/2891050468?t=00h12m00s): quadros revisados em 720,484677 s e 744,207020 s.

| Campo visível | Antes | Depois | Conclusão permitida |
|---|---|---|---|
| Rodada | 2-2 | 2-3 | Houve passagem para novo planejamento |
| Nível / XP | 4 / 2 de 10 | 4 / 4 de 10 | +2 XP neste exemplo |
| Ouro | 4 | 10 | Diferença observada; transações impedem atribuir tudo à renda |
| Loja | Alistar, Cinderling, Yorick, vazios | Pebbles, vazio, Scuttlecrab, Karma, Diana | Loja diferente; dois quadros não isolam todas as ações |
| Chances por custo | 55/30/15/0/0 | 55/30/15/0/0 | Corroboração visual da linha do nível 4 |

O overlay informa 18.3; não identifica o hotfix. Os quadros não comprovam fórmula completa de juros, estoque oculto, composição integral nem dano. Imagens e transcrição permanecem privadas no SSD; os hashes e limites estão em [online-evidence.json](evidence/dependencies-20261004/online-evidence.json).

## Confronto com as tabelas e regras

As [notas oficiais 18.3](https://teamfighttactics.leagueoflegends.com/en-au/news/game-updates/teamfight-tactics-patch-18-3/) confirmam que sacrifício Blackthorn, transformação de banco e conservação do pool têm regras específicas. Esses casos não podem ser simulados como simples bônus de atributos.

As tabelas de [chances da loja](https://www.tftraits.com/roll-odds/), [pool](https://www.tftraits.com/pool-sizes/) e [rodadas](https://www.tftraits.com/rounds/) foram registradas como referências suplementares. Elas ainda não são um pacote executável validado.

**Conflito aberto:** a [tabela de XP](https://www.tftraits.com/xp-to-level/) mostra 60 para chegar ao nível 8, enquanto as [notas 18.2 e sua atualização](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-2/) preservam a redução para 56. A observação anterior permanece documentada, mas esse conflito precisa de uma barra de XP de nível 7 em gravação com patch confirmado antes de fechar a validação do jogo atual.

## Dependências examinadas no pacote compilado

A auditoria recompila o catálogo selado e tenta inicializar núcleos diagnósticos das 12 estratégias. Não remove características para fazer o teste passar, não troca Nidalee AD por AP e não executa partidas completas. Os núcleos são subconjuntos de diagnóstico; sua aceitação não bastaria para validar todos os itens, posições ou a composição final.

| Núcleo | Primeiro bloqueio encontrado |
|---|---|
| Ravager | Inferno |
| Blossom AP | Blossom |
| Veigar | Ornn |
| Kha’Zix | Rival |
| Coven | Coven |
| Ashe / Draven | Bounty Seeker |
| Solar / Lunar | Solar |
| Ahri | Blossom |
| Nidalee / Aphelios | Aphelios; forma Nidalee AD também ausente |
| Sivir / Nidalee | Battlemage; forma Nidalee AD também ausente |
| Azir / Rammus | Blackthorn |
| Riftbeast | Riftbeast |

Além disso, o conteúdo compilado não contém `economy`, `match_rules`, `wisps` ou `persistent_rules`, e não há aprimoramentos do patch compilados. O motor genérico possuir alguns desses conceitos não significa que as regras sazonais estejam vinculadas. O pacote executável é 18.3; a memória estratégica mira 18.3B e desativações de 28/09.

### Próxima ordem de implementação

1. Vincular economia/loja/calendário ao patch, resolvendo o conflito de XP e identidades compartilhadas das formas.
2. Implementar Wisps/Blossom e sua ordem com lojas especiais.
3. Implementar Blackthorn, incluindo sacrifício e invocações de morte; depois os contadores persistentes Coven/Rival/Primal/Ivern/Draven.
4. Completar habilidades, formas, itens e interações das composições escolhidas; medir tempos e alvos em combates anotados.
5. Repetir os testes de dependências e comparar estratégias somente onde todas as regras envolvidas estiverem prontas.

## Reprodução e limites

```bash
PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m unittest training.tests.test_simulation_dependencies \
  training.tests.test_hex_simulator training.tests.test_event_combat

PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m training.simulator_lab.dependency_audit \
  --output docs/evidence/dependencies-20261004/compiled-audit.json
```

[Validação e hashes](evidence/dependencies-20261004/validation.json) · [Dependências compiladas](evidence/dependencies-20261004/compiled-audit.json) · [Tabelas e conflito de XP](evidence/dependencies-20261004/source-observations.json).

Nenhum candidato foi treinado ou promovido ao HUD nesta etapa. Testes executam cenários sintéticos e pequenos treinos temporários de regressão; isso não é treinamento do cérebro do produto. A identidade do código do motor mudou: checkpoints anteriores não podem ser reapresentados como avaliados contra esta revisão. Não foi criado instalador.
