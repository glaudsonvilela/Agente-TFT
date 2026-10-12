# Motor estratégico TFT Set 18 — preparação 18.4B

O pacote em `configs/strategy/TFTSet18/18.4B/` é uma referência versionada para
o futuro motor estratégico. O manifesto verifica o SHA-256 do catálogo. A
consulta em `knowledge/strategy_knowledge.py` só aceita conjunto e patch exatos.
Esse pacote pertence ao motor estratégico isolado; o rastreador e o
`ReplayDecisionEngine` não o carregam. `match001` continua em 18.3 e não deve
receber dados 18.4B.

## Conteúdo

- 65 identidades distintas de compra reconciliadas com Data Dragon 16.20.1.
- 91 entradas do Set 18, incluindo formas, invocações e unidades não compráveis;
  apenas as 65 identidades reconciliadas são marcadas como `shop`.
- Atributos base, custo, função, características, descrição e variáveis de
  habilidade de cada entrada; 36 características com marcos e variáveis.
- 776 entradas de itens/mecânicas do conjunto, 185 itens de núcleo e 592
  aprimoramentos. Catálogo de disponibilidade não significa que o efeito está
  habilitado na partida.
- 92 mudanças numéricas do patch 18.4 em campos `antes/depois` e 32 anotações
  da atualização 18.4B, todas ligadas às notas oficiais da Riot. Essas
  alterações permanecem separadas do snapshot do provedor: um hotfix não é
  aplicado por heurística a uma variável interna de nome parecido.
- Tabela de economia do pacote 18.3B anterior, marcada como **parâmetro de
  trabalho não confirmado para 18.4B**.

Fontes: [notas oficiais 18.4/18.4B](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/), [documentação do Data Dragon TFT](https://developer.riotgames.com/docs/tft), CommunityDragon 16.20 em inglês e português com hashes no manifesto, e a reconciliação local de 65 unidades com Data Dragon 16.20.1. A fonte CommunityDragon é complementar, não uma regra oficial de execução do servidor.

## Estado do cérebro

Uma identidade lida exatamente na loja pode ser consultada separadamente por
`knowledge/strategy_knowledge.py`. A resposta informa
`fact_type=patch_reference_not_observed_ownership` e
`combat_rules_verified=false`. Nenhuma ficha estratégica é injetada no
rastreador ou na decisão ao vivo nesta etapa.

O snapshot 16.20 ainda mostra, por exemplo, mana 30/120 para Varus e AD 55
para Mamãe Bicuda, enquanto as notas oficiais posteriores alteram esses
valores. Por isso, `stats_status` marca os atributos como **não reconciliados**
e os deltas oficiais ficam anexados à ficha. O motor não usa esses números
brutos como força de combate atual.

O snapshot tem 76 descrições de habilidade com marcadores `@...@` não
resolvidos. Esses textos e as variáveis não bastam para simular alvos, tempos,
efeitos simultâneos e passivas. A etapa seguinte é validar essas semânticas
contra partidas revisadas e converter apenas as regras verificadas em efeitos
executáveis. Treinar uma policy diretamente sobre descrições sem ação/resultado
revisados daria rótulos ruins.

A policy prevista é uma rede pequena em PyTorch para decisões discretas,
alimentada pelo estado estruturado e pelas saídas do motor matemático. O motor
continua calculando chances de loja, limites de pool, custo e orçamento; a
rede aprende a escolher entre ações legais e a estimar o resultado da
decisão. O vídeo é fonte de observações, não a entrada bruta do modelo de
estratégia: cada exemplo associa estado anterior, ação observada e estado
posterior. A reconstrução deve registrar também ações possíveis que **não**
foram escolhidas, a incerteza das leituras visuais e a perspectiva do jogador.
Sem uma ação legível, o trecho não entra no treino supervisionado. A primeira
etapa será imitação de decisões revisadas; resultados de partidas completas
servirão à avaliação posterior. Ainda não existe peso treinado dessa policy.

A auditoria das regras e o primeiro módulo Rust de ramificações econômicas
estão em `docs/strategy-basic-rules-audit-18.4b.md`. Eles calculam cenários
condicionais de vitória/derrota com juros, sequência e dano; não convertem uma
simulação em resultado observado nem afirmam conhecer o melhor lance.

## Comportamento durante a partida

O agente deve agir como jogador: manter um plano de composição e economia,
reavaliá-lo quando loja, oponentes, HP ou sinergias mudarem e comparar linhas
alternativas antes de recomendar a próxima ação. A policy recebe estado e
probabilidades estruturadas; ela produz ação, utilidade estimada, confiança e
evidências. A fala é uma camada posterior: só comenta quando a decisão ou o
plano muda de modo material e há evidência recente para explicar **por quê**.
Uma espera deliberada também pode ser a melhor ação, sem comentário repetido.

Frases como “suba de nível na rodada X” são hoje regras provisórias de
interface, não comportamento aprendido. Elas não devem ser usadas como rótulos
de treino. O objetivo para o modelo treinado é comparar alternativas conforme
o estado específico da partida, inclusive manter uma sequência de derrotas
quando o ganho esperado compensar HP e risco de eliminação. O comentário não
deve inventar peça, item ou porcentagem quando a observação está incerta.

## Partidas de Desafiante e treino no Akash

O arquivo `configs/training/challenger-strategy-18.4b.example.json` começa com
`games=[]`. Cada partida escolhida precisa ter:

```json
{
  "match_id": "id-estavel-da-partida",
  "set_key": "TFTSet18",
  "patch": "18.4B",
  "source_url": "https://...",
  "patch_evidence_url": "https://...",
  "rank": "challenger",
  "rank_evidence_url": "https://...",
  "usage_permission": true,
  "video_path": "/caminho/local/partida.mp4",
  "video_sha256": "64-caracteres-hexadecimais",
  "reviewed_actions_path": "/caminho/local/acoes.json",
  "reviewed_actions_sha256": "64-caracteres-hexadecimais"
}
```

O arquivo de ações revisadas contém `match_id` e uma lista `actions` com
`before_ms`, `action` e `after_ms` por transição. O validador recusa vídeos
ausentes, hashes diferentes, IDs duplicados, patch/rank sem evidência e ações
não revisadas. Divide por partida completa; pelo menos três partidas são
necessárias para treino, validação e teste. Isso prepara a seleção, **não**
inicia uma locação nem promove pesos.

```bash
python3 -m training.prepare_challenger_strategy \
  --selection configs/training/challenger-strategy-18.4b.example.json
```

Depois da seleção, a avaliação deve medir colocação final, decisões de compra,
economia, composição e adaptação ao adversário em partidas nunca usadas no
treino. A publicação do modelo exige comparação com o motor atual e revisão
dos erros; a GPU por si só não valida a estratégia.
