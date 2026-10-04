# Validação de combate, loja e progressão — 04/10/2026

## Prioridade atual — interações de economia, loja e sobrevivência

O usuário pediu a pausa de novas habilidades e prioridade aos sistemas que interagem mais nas decisões. Esta entrega conecta recursos e consequências condicionais; **ainda não é uma partida sazonal completa nem um coach treinado**. Os [sete cenários reproduzíveis](evidence/economy-interactions-20261004/examples.json) e o [registro dos testes](evidence/economy-interactions-20261004/validation.json) documentam esta etapa.

### Implementação

- `round_economy.py` reúne resultado declarado, sequência de vitórias/derrotas, ouro de vitória, juros, renda, dano ao jogador e XP natural. Cada projeção devolve um recibo dos cálculos. Eliminação interrompe a renda e o XP da próxima rodada. A fase impede pagamento duplicado.
- `match.py` pode aplicar essa projeção ao resultado de combate em um estado observado de laboratório. Conta sobreviventes entre os campeões originalmente possuídos, excluindo invocações, e devolve as peças e ofertas do eliminado ao estoque. Pareamento continua sintético; empate, número ímpar de jogadores e avanço automático do calendário são recusados neste modo.
- `state.py` consome primeiro rolagens gratuitas que expiram na rodada, depois créditos persistentes e finalmente ouro. A liquidação expira apenas os créditos temporários. A origem sazonal desses créditos ainda não é simulada.
- `shop_probability.py` calcula a chance de encontrar ao menos N cópias na próxima loja por programação dinâmica. Considera nível, esgotamento de classes de custo, retirada de cópias a cada oferta e devolução da loja atual antes de rolar. Reservas das lojas adversárias continuam fora do estoque disponível. O cálculo é exato dentro do modelo declarado de loja comum; não presume conhecimento do estoque oculto real.
- Os coeficientes comuns ficam em `configs/simulation/core/standard-economy-v1.json`, separados dos campeões, itens e chances de loja do pacote sazonal. Sua origem e pendências constam na própria tabela. Mesmo regras comuns podem mudar e exigem versionamento.

### Exemplo de interação

Cenário **hipotético**: 50 de ouro, nível 7 com 52 XP, 20 HP, estágio 4 e quatro derrotas seguidas. A projeção abaixo condiciona a próxima rodada a uma derrota com dois campeões inimigos sobreviventes; não prevê que isso acontecerá.

| Ação | Ouro após ação | Ouro na próxima renda | HP após derrota |
|---|---:|---:|---:|
| Guardar | 50 | 62 | 10 |
| Rolar pagando | 48 | 59 | 10 |
| Comprar XP e atingir nível 8 | 46 | 57 | 10 |
| Usar uma rolagem temporária gratuita | 50 | 62 | 10 |

O custo de rolar cruza a faixa de juros; a diferença final é de três de ouro. Comprar XP altera a chance da próxima loja. No cenário de estoque declarado, encontrar Nidalee AP passa de aproximadamente 3,53% no nível 7 para 10,31% no nível 8; seis cópias possuídas por outro jogador reduzem a segunda chance para 4,42%. Esses valores não representam a partida do usuário, não incluem a capacidade de comprar a oferta e não avaliam a força do tabuleiro.

### Evidência e limites

Foram executados **596 testes: 584 passaram e 12 foram ignorados**. Após os últimos ajustes de validação e calendário, passaram os **33 testes direcionados**, incluindo 11 casos de economia. Nenhuma partida completa foi simulada nesta etapa, nenhum exemplo virou rótulo de decisão e nenhum modelo foi promovido ao HUD.

As regras candidatas de sequência e dano foram reconciliadas com as notas oficiais [14.8](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-14-8-notes/) e [14.9](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-14-9-notes/). Isso documenta a origem dos valores; não prova que todos continuam idênticos no patch atual. A ordem dos juros, exceções sazonais e fronteiras de renda precisam de calibração atual.

O [VOD já observado](evidence/dependencies-20261004/online-evidence.json) corrobora uma passagem de 2 para 4 XP entre 2-2 e 2-3. Seu ouro de 4 para 10 não foi usado como prova de renda: houve transações entre os quadros. Fontes divergem sobre pagamentos em PvE; esse caso permanece recusado.

Próximas lacunas deste eixo: Wisps e seus créditos/recompensas; características e aprimoramentos econômicos; sequência completa de PvP/PvE/carrossel; pareamento e fantasmas; validação por replay com inventário e transações observáveis. As habilidades permanecem com 31/74 programas candidatos e as composições completas continuam em 0/12 validadas.

Reprodução dos exemplos (fornecer o pacote candidato compilado):

```bash
PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m training.economy_lab --content /caminho/candidate-18.3B.json \
  --output /caminho/economy-examples.json
```

## Histórico — complementação com revisão 18.3B e treinamento por preferências

**Continua incompleto.** A revisão candidata acrescenta nove programas de habilidade e uma cadeia de treinamento SFT → DPO. Nenhuma composição completa, partida sazonal ou melhoria de ranking foi validada. A [auditoria atual](evidence/rule-revision-20261004/compiled-audit.json) e o [registro de verificação](evidence/rule-revision-20261004/validation.json) substituem os números de implementação das seções históricas abaixo.

### Regras implementadas nesta revisão

- `ingestion/rule_revision.py` aplica alterações sobre o SHA exato da base. Cada mudança identifica o campo anterior, a fonte e a seção. Rejeita base modificada, caminhos sobrepostos e ausência de declaração das pendências. A base 18.3 permanece reproduzível.
- `configs/simulation/seasons/TFTSet18/revisions/18.3B-20260928.json` contém a revisão parcial. O nome 18.3B não concede paridade: a auditoria mostra `patch_label_match=true`, mas `exact_patch_match=false` enquanto a reconciliação estiver parcial.
- Akali AD: decide o dano adicional usando a queimadura existente antes do golpe; o próprio golpe não ativa retroativamente esse bônus.
- Camille: separa AD/AP do dano e escudo fixo; aplica o valor de AD restaurado no hotfix.
- Varus: exige que a linha escolhida inclua o alvo atual e aplica redução por inimigo atravessado.
- Warwick: cura a partir do dano efetivamente causado e da escala de AP; acumula velocidade de ataque durante o combate.
- Kobuko: cura periódica e substituição do próximo ataque. Rek'Sai: regeneração com janela temporária de três segundos e atordoamento adjacente. Vi: cura por ataque, cura ativa, velocidade, durabilidade e imunidade temporárias. Esses três continuam sem integração da função de tanque.
- Caitlyn: o terceiro ataque substitui o ataque comum, preservando seu crítico, sem inventar uma conjuração por mana. Xayah: cinco ataques substituídos, velocidade temporária e redução de armadura por impacto. A classificação desses ataques para todos os efeitos de itens ainda precisa de replay.
- Lux (dez entradas) e Nidalee AP recebem suas funções de mana candidatas. Diana e outros lutadores usam estágio explícito para a velocidade da função. O estágio 1 não é extrapolado.
- O codificador neural passa a `combat_hex_cells_stage_v3`: inclui estágio e presença dessa leitura por equipe. Checkpoints v2 não são reutilizados como se tivessem sido treinados com esse contexto.

| Medida | Base anterior | Revisão candidata |
|---|---:|---:|
| Entradas do catálogo, incluindo formas | 74 | 74 |
| Programas de habilidade | 22 | 31 |
| Entradas com programa e função de mana integrados | 7 | 25 |
| Programas aguardando função de mana | 15 | 6 |
| Entradas sem programa completo | 52 | 43 |
| Composições completas validadas | 0/12 | 0/12 |

Essas contagens não são porcentagens de fidelidade. Características, itens, formas alternativas, quatro estrelas, Wisps, aprimoramentos, calendário e efeitos entre rodadas têm dependências próprias. “Programa” significa código candidato testado em contratos isolados, não equivalência demonstrada ao cliente do TFT.

### Métodos de treinamento usados em LLMs, aplicados às ações

`training/decision_lab.py` executa aprendizado supervisionado por demonstrações (SFT), congela essa política como referência e aplica DPO a pares de ações preferida/rejeitada. É uma rede pequena que pontua ações candidatas; não é pré-treinamento de um modelo de linguagem.

A implementação segue a função de preferência da [equação 7 do artigo de DPO](https://arxiv.org/abs/2305.18290). Máscaras excluem ações ilegais, gradientes são limitados e a referência não recebe atualizações. Treino, validação e teste são separados por origem, partida e impressão digital da observação. Cada fase exige sua própria validação. O relatório distingue métricas sobre rótulos de melhora real no jogo.

O comando recebe um JSON `reviewed_action_features` com:

- `schema_version: 1`, nomes únicos em `feature_names` e um `evidence_registry` de caminhos e SHA256;
- `records` vinculados ao patch, SHA do conteúdo compilado e SHA do motor;
- para cada registro, origem/partida/observação, divisão, cobertura observável completa declarada e proveniência do rótulo;
- `mode: sft` com demonstração revisada, ou `mode: dpo` com preferência revisada;
- candidatos com `id`, `features`, `legal`, índice `chosen` e, no DPO, índice `rejected`.

A verificação confere os bytes das evidências e a consistência declarada. Ela **não certifica sozinha a correção semântica da anotação**. Exemplos provenientes de simulação exigem metadados de validação e sementes pareadas; o produtor desses exemplos continua responsável por validar as regras e os resultados. O exportador de sequências revisadas ainda não fornece exemplos com estado completo para essa interface.

Reprodução do comando, depois de produzir e revisar esse conjunto de dados:

```bash
PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m training.decision_lab --dataset CAMINHO_DO_DATASET_REVISADO.json \
  --content CAMINHO_DO_CONTEUDO_COMPILADO.json --output NOVA_PASTA_DO_CANDIDATO
```

Não foi iniciado treinamento de um coach de produção. Os testes usam exemplos sintéticos, verificando atualização real dos pesos, melhoria em pares sintéticos separados e preservação da referência. Isso testa o algoritmo, sem constituir evidência de competência em TFT.

### Reconciliação e pendências concretas

As [notas oficiais 18.3 e atualizações de setembro](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-3/) alteram campeões, recompensas e disponibilidade de conteúdo. A revisão registra essas fontes e mantém pendentes Blackthorn, Kha'Zix, LeBlanc, Teemo, Ashe, Draven e os IDs executáveis dos conteúdos desabilitados. A Riot descreve a mudança de Brambleback sem publicar a duração exata: esse tempo não foi inventado.

A curva de velocidade dos lutadores é sustentada pelas [notas oficiais 15.4](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-15-4-notes/) e sua função atual é confrontada com [TFTraits](https://www.tftraits.com/roles/). As cartas suplementares com ícones de AD/AP foram revisadas e têm SHA registrado. Essas páginas são mutáveis; não substituem calibração contra partidas do patch.

A fórmula exata de mana por dano dos tanques continua sem confirmação atual suficiente. A [descrição oficial das funções](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/roles-revamped-and-item-changes/) informa o comportamento, mas não fornece todos os coeficientes. Pesquisar fontes repetindo fórmulas antigas não resolve essa lacuna.

A auditoria dos 12 núcleos ainda recusa todos. Ravager agora avança até Shen; os demais continuam bloqueados por Ornn, Aphelios ou características sazonais. Permanecem ausentes os sistemas completos de Wisps, persistência e progressão de partida. Os vídeos/transcrições já catalogados não foram declarados observações completas automaticamente.

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
