# Validação de combate, loja e progressão — 04/10/2026

## Resultado atual — 10 mil cenários no BigBANANA e integração econômica

O usuário reiterou que **habilidades ficam fora desta versão** e autorizou prosseguir com testes dos sistemas restantes. Executamos **10.000 cenários de recursos**, com **zero falhas**, em **127,468 segundos**, pico de **26,83 MiB de RAM** do processo Python. São 8.000 cenários de Wisps, 1.000 de loja/equipamento/venda e 1.000 de recompensa através de carrossel. Cada cenário usa uma semente distinta. Os 27 Wisps passam por quatro políticas de Blossom, totalizando 108 combinações cobertas. Resultados de combate são entradas de teste declaradas.

O [registro de execução](evidence/seasonal-stress-10000-20261004/progress.json), os [10 mil registros comprimidos](evidence/seasonal-stress-10000-20261004/cases.jsonl.gz) e a [verificação](evidence/seasonal-stress-10000-20261004/validation.json) permitem auditar o lote. Os primeiros 150 registros reproduziram exatamente o piloto local entre Python 3.12 e 3.13. Um erro interrompe o executor e registra índice/semente; repetir o comando na mesma pasta não apaga a execução anterior.

### Integração ao código do aplicativo

- `hm/economy_budget.py` reutiliza os cálculos de XP e juros do simulador, com manifesto e hashes das tabelas. A curva de XP é conferida contra o denominador observado; nenhuma leitura incompatível gera compra.
- `ReplayDecisionEngine` devolve custo de evolução, XP remanescente, ouro restante, reserva e juros antes/depois. Quando a meta de evolução configurada exige mais ouro, emite uma decisão explícita de guardar até a quantia necessária. A escolha da meta continua sendo a regra de ritmo existente; **não é uma política neural aprendida**.
- `replay_coach.py` transforma a decisão em texto e frase para a fila de voz já existente. Exemplo verificado: “Guarde até 24 de ouro para subir ao nível 5.” Ao atingir 24, com leituras atuais e consistentes, passa à orientação de evolução por 4 de ouro, preservando 20.
- Tabelas carregam uma vez na inicialização; os testes proíbem leituras de arquivo durante a avaliação de quadros. O pacote WSL inclui os quatro módulos comuns necessários, sem dependência de tensor para esse cálculo. Importação foi testada em pacote mínimo isolado.
- [Ensaio da integração](evidence/seasonal-stress-10000-20261004/runtime-integration.json): 2.000 observações sintéticas, 1.000 orientações de evolução e 1.000 de economia; mediana 0,098 ms e p95 0,132 ms para decisão mais formatação. **Exclui captura, OCR, API e áudio físico**, portanto não mede o atraso total no Windows.

Validação adicional: três testes do executor passaram localmente e no servidor; quatro testes do adaptador passaram; a suíte do runtime executou 21 testes, com 20 aprovados e um ignorado. O arquivo `progress.json` do lote permanece no servidor em `/home/glaudsonvilela/agente-tft-trainer/data/stress-01d571f1976a/run-10000/`.

### Limites desta entrega

O lote verifica consistência da implementação candidata, não fidelidade integral ao jogo. **Zero partidas completas simuladas, zero novos pesos neurais treinados.** O cérebro estratégico, rótulos de decisões, resgates de Coven, aprimoramentos, distribuição completa e loot automático não são habilitados pelo sucesso desses testes. A integração econômica está no código; não foi gerado um novo instalador nem feito teste físico no Windows nesta etapa. Não se marcou nenhuma habilidade como implementada ou necessária para aprovar este lote restrito.

## Histórico da integração anterior

## Revisão atual — elegibilidade, preços e lojas dos Wisps

**Não está pronto para instalar um novo cérebro.** Esta revisão corrige dependências do simulador; não gerou uma política treinada nem executou partidas completas. [Validação](evidence/seasonal-offers-20261004/validation.json) e [checagem no BigBANANA](evidence/seasonal-offers-20261004/bigbanana-preflight.json).

### Lacunas corrigidas nesta revisão

- Dano comum dos estágios 3/4 corrigido para **6/7**, conforme a [alteração oficial 16.1](https://teamfighttactics.leagueoflegends.com/en-gb/news/game-updates/teamfight-tactics-patch-16-1/). A tabela `standard-economy-v2.json` substitui a anterior nos laboratórios; v1 e relatórios antigos permanecem históricos. Testes mostram a diferença na eliminação e no recebimento da próxima renda.
- **27 Wisps / 54 programas candidatos**: os 15 anteriores mais Experienced, Bronze Spoon, Grow Up, Lucky 7, Life Debt, Drought, Flood e All Ones/Twos/Threes/Fours/Fives. Há **18 pares de IDs** reconciliados com o catálogo; os demais continuam sem identidade externa confirmada.
- Custos separados por variante: Die Roll fortalecido custa 3; Experienced fortalecido custa 0; Bronze Spoon fortalecido custa 2. Notas oficiais 18.2/18.3 prevalecem sobre o catálogo anterior para Payday, Blood Money, All Fours e All Fives.
- Oferta valida janela de rodadas, planejamento PvP, ouro após pagar a atualização, vida, sequência, quantidade de unidades de uma estrela e restrição de Coven. Condições desconhecidas são recusadas. A cadência e o sorteio completo **não** são inferidos dessa lista parcial.
- Healing Pool exige histórico explícito para validar o intervalo de dez rodadas entre ofertas. O histórico persiste; calendários alterados no meio da sessão são recusados. Uma captura sem histórico não equivale a nunca ter visto a oferta.
- Life Debt calcula ouro com a vida faltante antes da cura. Drought/Flood alteram a sequência usada para a próxima renda e não convertem uma sequência oposta. XP, créditos de rolagem e custos de compra usam as operações comuns.
- Lojas forçadas por custo reutilizam o estoque compartilhado: devolvem a reserva anterior, não retiram ofertas dos adversários e não fabricam cópias quando o custo está esgotado. Esse último comportamento ainda exige confirmação em replay. Não há cópia do catálogo por compra nem novo serviço em memória.

### Verificação e limites

Suíte local: **624 testes, 612 passaram e 12 ignorados**, em 28,257 s. No contêiner isolado do BigBANANA, **38 testes direcionados passaram**, em 0,459 s. Os pequenos treinos sintéticos internos da suíte são testes de componentes e não equivalem ao treino do coach. O [exemplo de recursos](evidence/seasonal-offers-20261004/walkthrough.json) continua identificado como observação declarada, com zero partidas/combates simulados e zero rótulos de treino.

O contêiner mantém 1,5 CPU e 1 GiB de RAM; a checagem encontrou cerca de 4,5 GiB livres no disco do servidor. O pacote foi validado em uma pasta isolada. Não houve promoção de modelo ou substituição do serviço em produção.

Ainda faltam: sorteio/cadência/condições completas de todos os Wisps; resgates de Coven com escolha de unidades e itens; aprimoramentos; lojas especiais e prioridade; loot PvE/carrossel; pareamento/fantasmas; integração da partida completa; calibração em replay e combate restante. As habilidades permanecem pausadas conforme a solicitação. **O lote de 10 mil partidas e o treinamento do novo cérebro não começaram.**

A [reconciliação de fontes](evidence/seasonal-offers-20261004/source-reconciliation.json) registra também divergências abertas: a fonte suplementar atual lista 174 Wisps, enquanto o inventário anterior tinha 148; e uma recompensa de Coven diverge das notas oficiais. Não se calcula percentual global de conclusão com esses denominadores.

## Histórico da revisão anterior

## Eventos sazonais e preparação do lote de 10 mil — 04/10/2026

**Etapa parcial, com código executável e testes no BigBANANA. Não há 10 mil partidas completas em execução.** O [relatório do servidor](evidence/seasonal-events-20261004/bigbanana-preflight.json) identifica cada impedimento; a [verificação](evidence/seasonal-events-20261004/validation.json) registra os hashes e os testes. As habilidades continuam pausadas por solicitação do usuário.

### O que foi acrescentado

- Quinze Wisps de recursos, com versões normal e fortalecida: Beggar's Wisp, Coin Flip, Die Roll, Freeroller, Healing Pool, Blood Money, Fertilize, Take One With Ya, Good Loss, Golden Road, Minor Gambit, Major Gambit, Payday, Pocket Change e Sinister Deal. São **30 programas candidatos de um inventário de 148 Wisps**, com valores e fontes separados do motor.
- Ofertas observadas como uma camada sobre a quinta unidade da loja. A unidade permanece reservada no estoque; a oferta expira ao encerrar o planejamento. Compra valida o ouro antes de aplicar recompensa/reembolso. Compra, atualização e falhas preservam o registro de cópias e o estado aleatório original.
- Política econômica candidata de Blossom 3/5/7/9: fortalecimento aplicado após combate, reembolso e limite de uma/duas compras. Cadência é descrita nos dados, mas o seletor automático ainda não a executa: a oferta é um dado observado. Blossom 11 é recusado. Atributos de combate da característica permanecem fora deste módulo.
- Essência de Coven 3/4/5 calculada por abates declarados e resultado, com valores de derrota do patch 18.3. Identidades duplicadas e campeões na reserva não contam como membros novos. A escolha de continuar acumula Essência; resgate aleatório e Coven 7 permanecem pendentes.
- Recompensas que persistem por vários combates têm contadores separados do calendário. Carrossel/PvE não consomem contadores de combates contra jogadores. Resultados repetidos, fases inválidas e campos de efeito desconhecidos são recusados.
- Calendário candidato explícito de 1-1 até 8-7, com classificação PvP/PvE/carrossel e marcação de aprimoramentos. Transições não pulam rodadas. Rodadas de aprimoramento param por falta do handler; nos limites especiais, o laboratório só aceita recursos medidos, identificados como observação externa.
- Eliminação por custo de vida ou combate devolve unidades/ofertas ao estoque. O modelo comum de economia, a busca e os dois motores de combate recusam estados sazonais que não sabem interpretar, evitando gerar rótulos com efeitos omitidos.

### Evidência executável

A [sequência demonstrativa](evidence/seasonal-events-20261004/walkthrough.json) atravessa 2-2, 2-3, 2-4 e 2-5. Mostra uma recompensa de Golden Road amadurecendo após três PvPs, preservada durante o carrossel. Resultados foram declarados, os recursos do carrossel foram mantidos constantes para o exemplo, e **nenhum combate foi simulado**.

A suíte ampla executou 609 testes: 597 passaram e 12 foram ignorados. Após os últimos ajustes e quatro novos testes, os 28 testes direcionados passaram localmente e no contêiner do BigBANANA. Também passaram os seis testes do modelo de valor, incluindo a recusa de estados sazonais que seu codificador ainda não representa. Não houve treinamento de uma rede de decisões nesta etapa.

```bash
PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m training.seasonal_lab --content /caminho/candidate-18.3B.json \
  --output /caminho/seasonal-walkthrough.json

PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m training.simulator_lab.batch_preflight \
  --content /caminho/candidate-18.3B.json \
  --events configs/simulation/seasons/TFTSet18/events/18.3B-economy.json \
  --output /caminho/batch-10000-preflight.json --matches 10000 --workers 1
```

A segunda chamada retorna código 2 enquanto bloqueada. É uma checagem, não um agendador: não iniciará trabalho posteriormente por conta própria.

### BigBANANA e o lote

O servidor possui quatro CPUs e aproximadamente 15 GiB de RAM total. Na verificação, o contêiner do treinador estava limitado a **1,5 CPU / 1 GiB**, com cerca de 4,5 GiB livres no volume. O código foi colocado em uma pasta isolada de validação, sem reiniciar os serviços. Os números exatos e o estado do contêiner constam no relatório.

O lote solicitado permanece em **0/10.000 partidas completas, não iniciado**. Faltam distribuição/identidades dos Wisps, demais Wisps, tabelas e escolhas de resgate, aprimoramentos, lojas especiais e sua prioridade, PvE/loot/carrossel efetivos, pareamento/fantasmas, integração do ciclo completo e os combates ainda incompletos. A classificação do calendário e os recibos de recursos não substituem essas regras.

Antes de estimar duração ou RAM para 10 mil partidas, é necessário executar um piloto de partidas completas com a mesma versão do motor. Os tempos históricos de combates isolados não foram extrapolados. A checagem não possui um botão `ready=true`: mesmo relatórios de cobertura alterados não habilitam o executor sintético como partida sazonal.

### Fontes e calibração pendente

A [procedência](evidence/seasonal-events-20261004/source-observations.json) registra as notas oficiais [18.1](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-1/), [18.3](https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-3/), o catálogo selado e a lista suplementar [TFTraits](https://www.tftraits.com/wisps/). Ordem de pagamentos, persistência, limites de cura e descrições ambíguas continuam candidatos sujeitos a replay. Nenhuma lacuna foi marcada como resolvida apenas por haver texto de referência.

## Histórico — interações de economia, loja e sobrevivência

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
