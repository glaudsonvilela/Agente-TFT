# Validação de combate, loja e progressão — 04/10/2026

## Resultado

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
