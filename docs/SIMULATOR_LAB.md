# Simulação e treinamento da política

## Coach sem habilidades — etapa separada

O [experimento por atributos](COACH_ATTRIBUTE_POLICY.md) acrescenta alternativas
de rolagem, composição, posição e equipamentos e uma rede pequena para ordená-las.
Seu treino é destilação de um objetivo explícito em estados sintéticos, com
teste reservado; não equivale a partidas completas ou ao PPO descrito abaixo.
A confirmação visual foi adiada por solicitação do usuário e ainda é necessária
para entregar essas quatro categorias automaticamente sobre a captura.

## Validação das dependências

A [validação de 04/10/2026](DEPENDENCY_VALIDATION.md) corrigiu falhas na sequência
de rodadas, loja e recusa de aprimoramentos não suportados. A suíte passou com
550 testes, 12 ignorados. A auditoria dos 12 núcleos estratégicos ainda recusa
todos por dependências ausentes. Inclui revisão online de YouTube/Twitch,
evidências visuais e conflito explícito na curva de XP. Nenhum peso promovido.

## Pesquisa estratégica antes da próxima simulação

A [memória sazonal de 04/10/2026](SEASONAL_STRATEGY_MEMORY.md) registra 19 fontes,
15 grupos de mecânicas e 12 estratégias condicionais para 18.3B + hotfix de 28/09.
Inclui correções de Blackthorn, terreno de Ivern e lojas especiais, além de
condições de entrada/saída e comparações planejadas. É conhecimento de pesquisa,
sem atualização de pesos, nova simulação ou promoção para o HUD. O perfil
executável 18.3 continua separado do conhecimento do hotfix.

## Estado real

Foi integrado um laboratório de oito jogadores com loja, ouro, XP, banco,
evolução de estrelas, rodadas, combate por ticks, eliminação e PPO. O motor é
TFT_GOAT (MIT), fixado em `d5358e9402569f745bea81b61c5aed0500c57d66`.
Seu código e licença são preservados pelo bootstrap. Não há cópia de código
upstream nos novos módulos de integração.

**Ainda não é um simulador completo do Set 18.** O laboratório usa oito campeões
sintéticos e regras aproximadas de uma base Set 17. O agente PPO não escolhe hexágonos
ou a identidade dos itens equipados; o upstream usa formação/equipamento
automáticos e sua observação contém contagens de itens. Esses limites impedem
usar o candidato nas dicas do replay. Não se pode trocar apenas o JSON de
campeões e chamar esse motor de compatível com outro set.

O comando padrão recusa treinamento `current-patch`. Só `--profile synthetic-lab`
permite executar o laboratório. `configs/simulation/laboratory-v1.json` documenta
a configuração; não contém um interruptor para liberar recomendações.

## Preparação e execução local

Na raiz do repositório, usando Python 3.12:

```bash
python3 -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r training/simulator_lab/requirements.txt
bash scripts/bootstrap_tft_goat.sh
.venv/bin/python -m training.simulator_lab.coverage --output trainer/data/simulation-coverage.json
.venv/bin/python -m training.simulator_lab.selfplay --profile synthetic-lab --output trainer/data/policy-runs/lab-v1 --iterations 100 --seconds 3600 --threads 2 --memory-mib 1200
```

A auditoria requer o release sazonal local apontado em
`configs/catalog/active-knowledge-release-v1.json`; não baixa dados escondidos.
Para continuar o mesmo candidato, repita o comando com `--resume`, mantendo
semente, tamanho do lote e configuração. `--iterations` são lotes **adicionais**.
O limite de tempo vale por invocação. É possível usar até 100.000 lotes, com
limite obrigatório de até 24 horas, e retomar depois. Não existe reinício infinito.
`--matches 500` acrescenta um alvo de 500 partidas completas no total, incluindo
as restauradas. O treino para no primeiro limite atingido (partidas, lotes ou tempo).

Para parar, crie `STOP` na pasta do experimento ou envie SIGTERM. O lote corrente
é descartado e o último checkpoint completo fica disponível. Remova `STOP`
antes de retomar. Uma partida parcial é descartada na retomada; a próxima usa
uma semente nova, e só partidas terminadas entram na contagem. O worker usa lock
exclusivo, valida o commit upstream, hashes e configuração na retomada e mantém
apenas os dois checkpoints mais recentes. O histórico contém uma linha por lote.

O limite de memória local é cooperativo, conferido na coleta e entre combates.
O contêiner impõe adicionalmente limites rígidos de CPU/RAM. Não existe requisito
de GPU nesse laboratório. Ainda é necessário medir o custo do futuro motor
com todas as habilidades do set atual.

## Avaliação separada

```bash
.venv/bin/python -m training.simulator_lab.evaluate --run trainer/data/policy-runs/lab-v1 --output trainer/data/policy-runs/lab-v1/evaluation.json --games 8
```

Compara a rede inicial com o candidato contra adversários programados, nas mesmas
sementes e cadeiras. As sementes de avaliação ficam em outro domínio. Uma
amostra pequena ou uma queda de loss não comprova melhora em TFT real. O relatório
mantém `training_improvement_proven=false` e `runtime_promoted=false`.

## Catálogo dos testes

```bash
.venv/bin/python -m training.simulator_lab.catalog_sessions --source /caminho/sessao --source /caminho/sessao.zip --output trainer/data/replay-catalog/catalog.json
```

Verifica SHA dos arquivos e pixels, dimensões e entradas repetidas de ZIP; recusa
arquivos alterados ou duplicatas conflitantes. Deduplica frames por pixels sem
copiar os vídeos. O índice preserva caminhos locais e fica ignorado pelo Git.
Previsões anteriores não viram rótulos. Patch e identidade de partida precisam
ser revisados antes de dividir treino e avaliação; sessões do mesmo jogo não
podem aparecer nos dois lados. Geometria da tela e rótulos sazonais ficam separados.

## BigBANANA e painel

O painel existente passa a ler `policy-runs/*/progress.json` ao lado do banco do
trainer. Exibe partidas terminadas, combates, transições, atualizações, memória,
tempo de CPU e verificação do checkpoint. Esses números não alteram os contadores
de simulações de decisões enviadas pelo HUD, nem `simulator_ready` dessa API.
A auditoria de cobertura é exibida separadamente.

O worker opcional está em `trainer/compose.policy-lab.yml`. Monte o mesmo diretório
de dados do trainer e ajuste UID/GID para seu proprietário. Execute separadamente:

```bash
mkdir -p trainer/data
TFT_WORKER_UID=$(id -u) TFT_WORKER_GID=$(id -g) docker compose -f trainer/compose.policy-lab.yml up --build
```

Não publica portas, não usa rede durante o treino, tem limite de 1,5 CPU e
1,5 GiB e não reinicia automaticamente. Para retomar acrescente `--resume` ao
comando do serviço. A integração no servidor e a construção dessa imagem precisam
ser verificadas no host de destino; uma execução local não comprova implantação.

## Critérios para substituir o laboratório pelo simulador do patch

1. Completar e verificar atributos, fórmulas por estrela e handlers de todas as
   habilidades; textos e ícones não implementam efeitos de combate.
2. Implementar efeitos de itens, receitas, interações, sinergias, aprimoramentos,
   economia e mecânica sazonal com fixtures e procedência por patch.
3. Representar e permitir decisões sobre os 28 hexágonos, identidades dos itens
   equipados e inventário, sem reduzir tudo a contagens.
4. Rotular unidades próprias, estrelas, posições e itens em combates reais;
   validar dano, alvos, tempo e resultado contra partidas independentes.
5. Integrar estado observado ao simulador, bloquear campos desconhecidos e
   comparar política treinada com baselines em sementes e partidas separadas.
6. Só promover um candidato após comprovar cobertura e benefício. Salvar pesos
   novos não equivale a uma política melhor.

## Núcleo próprio com posições e itens (04/10/2026)

`trainer/simulation/{state,hexgrid,combat,match,search}.py` acrescenta um segundo
motor, próprio e independente do upstream. A configuração versionada
`configs/simulation/hex-lab-v1.json` contém **três unidades sintéticas**, não
campeões oficiais. Não foi ligado ao PPO acima nem às recomendações do HUD.

Implementado e exercitado:

- Estado explícito de oito jogadores: ouro, XP, HP, loja reservada do pool
  compartilhado, banco, estrelas, posições e identidades dos itens.
- Ações atômicas de comprar, vender, subir nível, atualizar/travar loja,
  mover/trocar unidades e equipar/combinar componentes no portador. Comprar a
  terceira cópia funciona com banco cheio; falhas preservam recursos e RNG.
- Malha de 8×7 hexágonos, alcance e caminho sem atravessar unidades.
- Combate com resistências, crítico, mana, valores separados por estrela,
  dano direto, dano periódico e escudos com expiração própria.
- Rodadas com renda, XP, combates e eliminação. O perfil declara explicitamente
  emparelhamento aleatório com folga, dano fixo e ausência de loot/sequências;
  isso não reproduz as regras sazonais do TFT.
- Busca UCT com orçamento e alternativas de posições/itens. 500 caminhos de
  busca não são 500 partidas completas. Os valores vêm do combate experimental.

Sinergias, habilidades ou efeitos de item sem handler provocam erro antes do
combate. Prioridade de itens/stacks durante fusão permanece não suportada.
Mira, cadência, projéteis, interrupções e outras interações ainda exigem validação
contra partidas reais. A disponibilidade dos handlers genéricos não altera
`executable_abilities` do catálogo oficial.

```bash
.venv/bin/python -m unittest training.tests.test_hex_simulator training.tests.test_source_corpus -v
.venv/bin/python -m training.hex_lab --output trainer/data/hex-lab-v1/report.json --matches 10 --paths 500 --seconds 120
```

No BigBANANA, a execução de integração completou dez partidas, 527 combates
e uma busca de 500 caminhos em 8,58 s, com pico de 36,8 MiB (Python do servidor).
A busca isolada levou 2,55 s. A execução local usou outro runtime e mediu
11,20 s/140,1 MiB. São medições deste cenário sintético, sem captura, OCR ou voz.
Os relatórios estão em `docs/evidence/hex-simulator-20261004/`.

O PPO anterior concluiu seu alvo de **500 partidas** no BigBANANA: 3.738.210
transições, 60.436 passos de otimização e 40.177 chamadas de combate. Checkpoint
`8afc57a246da3260f94a75a22134fac12a1589900f7c56634953f780351b5c4e`.
Em 16 sementes de avaliação por versão, contra adversários programados, a
colocação média inicial foi 7,9375 e a treinada 1,8125. Esse resultado mostra
melhora nessa avaliação sintética; não comprova habilidade em TFT real.

No servidor: `tft status` mostra o treino; `tft simulador` mostra a última
execução do núcleo; `tft fontes` mostra a última cópia do corpus de referência.
Os dois últimos comandos leem relatórios salvos, não prometem atualização ao
vivo de processos que executam no Ubuntu.

## Motor de eventos e rede de valor (04/10/2026)

O modo `combat_version: 2` acrescenta `event_combat.py`, `modifiers.py` e
`traits.py`. O primeiro motor permanece disponível para reproduzir o laboratório
anterior. Nenhum dos dois constitui o simulador completo do patch.

### O que passou a executar

- Fórmulas por estrela, AD/AP/HP, valor fixo, percentual da base, percentual do
  total e multiplicador como operações distintas. Campos desconhecidos falham.
- Ataques com preparação e projéteis; mana excedente, regeneração e bloqueio
  durante conjuração; resistência, penetração, redução, amplificação e durabilidade.
- Dano direto/periódico, cura, Ferimento, vampirismo, escudos independentes,
  controle de grupo e imunidade, execução, deslocamento, transformação e invocação.
- Efeitos periódicos com cadência própria, snapshot explícito, acumulação ou
  renovação do mais forte. Renovar uma queimadura não reinicia continuamente seu
  relógio. Efeitos já lançados podem continuar após a morte da fonte.
- Gatilhos de ataque, conjuração, dano, eliminação/assistência, morte, vida baixa,
  fim de escudo e passagem do tempo; limite de ativações e cooldown.
- Sinergias por identidade distinta, emblemas e contribuições extras. Unidades
  repetidas e banco não inflam a contagem. Bônus de equipe e de membros separados.
- Bônus permanentes e ouro obtidos em combate são aplicados uma vez ao estado
  clonado da rodada; vida temporária e invocações não viram unidades possuídas.

Essas são capacidades do motor. Cadência, alvos, efeitos e interações ainda
precisam de comparação independente com o jogo. Existem testes de contratos e
interações; eles não substituem essa comparação.

### Catálogo e cobertura verificável

`training.compile_effects` exige o hash da release selada e compila as regras de
`configs/simulation/set18-effects-bindings-v1.json`. Geometria, observações da tela,
fontes sazonais e pesos continuam separados. A compilação não modifica a release
nem mistura automaticamente 18.3 com 18.3B.

| Bloco | Estado desta entrega |
|---|---|
| Habilidades | 4 templates candidatos: Veigar, Karma, Cassiopeia e Ahri; 70 entradas do catálogo ainda sem handler |
| Itens/componentes | 17 handlers candidatos; a pertinência dos 3.444 registros globais ao conjunto atual não está validada |
| Sinergias | 4 de 36: Colosso, Enfeitiçador, Fumegante e Flora Fatalis |
| Aprimoramentos | Motor aceita modificadores/gatilhos; catálogo sazonal ainda sem handlers |
| Partida de oito jogadores | Loop sintético anterior; agenda, PvE, carrossel, loot, sequências, dano ao jogador e oponentes reais pendentes |
| Eventos do conjunto | Fagulhas, lojas especiais, invocações sazonais e escolhas próprias do conjunto pendentes |
| Itens especiais e fusões | Radiantes/artefatos, consumíveis, transbordamento e prioridade de itens/stacks na fusão pendentes |
| Validação em replay | 0 habilidades promovidas; ataque/movimento/projéteis/cast/DOT possuem hipóteses explícitas |

As 74 entradas incluem formas; não são uma declaração de 74 campeões distintos.
O relatório lista os IDs ausentes. Habilidade, item, aprimoramento ou sinergia
ativa sem implementação interrompe a execução. Não recebe um bônus genérico.
Espátula possui um campo numérico ainda não identificado e continua bloqueada.
Uma fonte secundária diverge no dano da Cassiopeia; a configuração registra o
valor oficial 425 e mantém a divergência documentada. Funções de tanque,
progressão de lutador e crítico acima de 100% não recebem conversão inventada.

### Medição e aprendizado executados

`training.event_lab` amostra tabuleiros de 2–4 campeões por lado dentro do
subconjunto implementado. Faz 500 **combates**, não 500 partidas completas.
400 sementes entram no treino e 100 ficam reservadas. A inversão dos lados só
ocorre depois dessa divisão, evitando que versões espelhadas vazem entre grupos.

- BigBANANA, CPU limitada a 2 núcleos/512 MiB: **500 combates em 13,34 s**, pico
  **44,66 MiB**, média **25,74 ms** e p95 **43,23 ms** por combate.
- Rede de valor de **3.203 parâmetros**, **780 atualizações** em 60 épocas.
- Acerto reservado: **91/100**, contra **61/100** do resultado majoritário.
  Entropia cruzada caiu de **1,2206** para **0,2758**.
- Checkpoint do servidor: `66043d4b1d7aac78f334b619253945241c9b4a5edfda5dd9927c8d0dd263ee30`.
- A repetição local/servidor gerou o mesmo hash dos cenários/resultados:
  `db47d74c5fd583116bf04e772dbdf30ff6bf87acfe36865fcd7132dc4b39e189`.

O alvo aprendido é o resultado do motor candidato, incluindo suas hipóteses.
Isso não comprova melhoria de decisões em TFT, aprendizado dos vídeos ou
qualidade das dicas. A rede anterior de PPO também permanece separada.
`current_patch_training_ready` e `runtime_promoted` continuam falsos.

Evidências numéricas em `docs/evidence/event-simulator-20261004/`; cenários,
pesos e conteúdo compilado ficam no SSD e no diretório privado do servidor.
O relatório final do servidor inclui hashes do código executado, conteúdo e
checkpoint. O relatório local documenta a primeira execução, anterior à adição
desse campo de identidade; não deve ser usado como atestado do código posterior.

```bash
.venv/bin/python -m training.compile_effects \
  --release knowledge/releases/TFTSet18/18.3/0674657d3f7c165d37045fbd45d8f7c56b20aef064660e6906c3985f0c8a0299 \
  --output datasets/event-lab/content.json
OPENBLAS_NUM_THREADS=1 .venv/bin/python -m training.event_lab \
  --content datasets/event-lab/content.json --output datasets/event-lab/run-novo \
  --combats 500 --epochs 60 --seconds 180
tft simulador
```

Use um diretório de saída novo para preservar os dados anteriores. Um arquivo
`STOP` nesse diretório interrompe entre combates. O orçamento também limita o
treino. No BigBANANA, `tft simulador` lê os contadores atuais durante a execução
e mostra métricas finais depois; cada consulta lê novamente o relatório. O lote
acima terminou, portanto não aparece como treino continuamente ativo.

## Separação sazonal consolidada — pacote v3

A configuração monolítica `set18-effects-bindings-v1.json` permanece como
registro histórico. O compilador agora usa, por padrão, o manifesto explícito
`configs/simulation/seasons/TFTSet18/18.3/manifest.json` e quatro componentes:

| Componente | Responsabilidade |
|---|---|
| `champions.json` | Habilidades, identidade de função e tempos específicos de cada campeão |
| `items.json` | IDs, componentes, unidades dos atributos, gatilhos e fórmulas de itens |
| `traits.json` | Patamares, bônus, contadores e efeitos das sinergias |
| `profile.json` | Progressão por estrela, métricas das funções, hipóteses temporais e seleção do experimento |

Os algoritmos de geometria, movimento, eventos, modificadores, controle e ações
permanecem em `trainer/simulation`. Eles recebem os dados compilados. A tradução
genérica em `ingestion/simulation_bindings.py` e `training/compile_effects.py`
substitui apenas campos numéricos declarados; não executa expressões textuais.
Não há ramificações por nome/ID de item ou sinergia no compilador. Regeneração de
mana e multiplicadores por estrela também saíram do código para o perfil.

O manifesto fixa o hash de cada arquivo e a release do catálogo. Arquivo
alterado, campo desconhecido, divergência de aliases ou ID ausente interrompe a
compilação. Uma atualização deve criar outro pacote/manifesto, selecionar sua
release, compilar e comparar resultados; não substituir automaticamente dados
de replays anteriores. O artefato compilado tem `schema_version: 3`; o runner
recusa versões anteriores e pede recompilação explícita.

O relatório, esquema de entrada do modelo e identidade do treino guardam patch,
hash da release, hash das regras e hashes dos quatro componentes. Isso permite
separar métricas de diferentes patches. `tft simulador` também exibe o patch e a
identidade das regras. O esquema do modelo agora inclui a identidade do código
e o checksum dos pesos. A adoção desses pesos no HUD continua desativada.

### Novos efeitos

- **Determinação Titânica:** ataque e dano recebido compartilham o mesmo limite
  de acúmulos; o bônus final acontece uma vez. Duas cópias têm contadores próprios.
- **Último Sussurro:** redução de armadura com duração e renovação, sem soma de
  debuffs iguais; gatilho restrito a dano de ataque/habilidade.
- **Mercúrio:** imunidade temporária a controle e ganho de velocidade por tempo.
- **Juramento do Protetor:** mana inicial e recompensa de mana/escudo no limiar
  de vida; a interpretação de uma ativação por combate ainda exige replay.
- **Lutador:** bônus de vida de equipe e de membros declarados separadamente.
  A ordem do percentual sobre a vida total continua como hipótese explícita.
- **Vanguarda:** escudo inicial, escudo no limiar de vida e, no patamar adequado,
  durabilidade condicionada à presença de qualquer escudo ativo.

Total atual: **4 habilidades, 21 itens/componentes e 6 sinergias candidatos**.
A validação em replay permanece em zero e o simulador sazonal completo continua
pendente. O conjunto de primitivos suporta mais efeitos que o catálogo já ligado
a eles; esses dois números não devem ser confundidos.

### Verificação desta versão

53 testes direcionados passaram. A suíte de treinamento executou 503 testes,
12 pulados, nenhuma falha. Vinte cenários anteriores produziram exatamente os
mesmos resultados após migrar as regras para arquivos separados.

No BigBANANA, o conteúdo foi recompilado a partir do manifesto e da release
selada, com o mesmo hash do build local. O lote ampliado incluiu os quatro itens
novos: **500 combates em 16,27 s**, pico do processo **44,70 MiB**, p95 **57,02 ms**.
A rede de **4.227 parâmetros** fez **780 atualizações** e obteve **85/100** nos
cenários reservados, contra **62/100** do baseline majoritário. Esse conjunto
de cenários mudou; o resultado não é diretamente comparável aos 91/100 do lote
anterior e não demonstra acurácia no jogo real.

Evidências: `docs/evidence/event-simulator-20261004/season-v3-*.json`.
Código e catálogo privados no servidor: `agente-tft-trainer/event-lab-season-v3`.
Dados, pesos e relatório: `agente-tft-trainer/data/event-lab-20261004-season-v3`.

### Prioridade: habilidades — auditoria de 04/10/2026

O pacote `configs/simulation/seasons/TFTSet18/18.3/champions.json` agora inventaria
as **74 entradas do catálogo selado**. Isso inclui formas de Lux; não equivale a
74 campeões distintos nem a todas as formas possíveis do jogo.

Estado desta etapa:

- **22 programas candidatos**, antes 4. Os 18 adicionados são Diana,
  Fiddlesticks, Hecarim, Shen, Soraka, Azir, Nidalee AP, Ivern e 10 formas de Lux.
- **52 entradas bloqueadas**, cada uma com suas dependências em `blockers`.
  Uma entrada bloqueada não recebe uma habilidade genérica substituta.
- **7 programas com papel de mana vinculado**. Os outros 15 podem ser
  exercitados em testes isolados; a compilação de combate continua bloqueada.
  Mesmo os 7 dependem da cobertura das sinergias ativas e de calibração temporal.
- **0 validados em replay**. Não foi iniciado novo treino nem atualizado o HUD.
- Akali AP, Gromp AD, Kog'Maw AP, Master Yi AP e Nidalee AD são lacunas adicionais
  fora das 74 entradas. Quatro estrelas também não estão cobertas integralmente.

O motor neutro recebeu seleção da melhor linha, distribuição de projéteis,
sequências com alvos fixados, marcas por conjurador, condições por número de
conjurações, ataques fortalecidos com cargas, escudos críticos e limpeza de
controle. Coeficientes, formas, escolhas de alvos e hipóteses temporais ficam no
pacote sazonal. As formas de Lux compartilham uma identidade para não inflar
contagens de campeões distintos.

Os testes verificam separadamente: AP versus dano de ataque; seis orbes totais
de Diana; cura de Fiddlesticks não multiplicada pelos alvos; resistência e
atordoamento de Hecarim; ataques substituídos de Azir; escudo e ataques do aliado
de Shen; seleção da terceira lança de Nidalee; escudo crítico e limiar de Ivern;
marcas de Soraka; atenuação e bônus das formas de Lux; remoção e renovação de
bônus sem acúmulo indevido. Esses testes usam atributos explícitos de laboratório,
não adversários reconstruídos de partidas reais.

Limitações de interpretação continuam explícitas nas notas de cada programa:
ordem/velocidade dos projéteis, cadência de drenos, escolha de aliados de Ivern,
compartilhamento de marcas entre duas Sorakas, geometria da linha e recuperação
dos ataques. O ataque fortalecido dado por Shen usa AP e autoria do conjurador
neste candidato; autoria de dano, interação com itens do aliado e snapshot versus
AP no impacto precisam de replay independente. O modelo de soldados de Azir
representa comandos de ataque, sem posição independente dos soldados.

As fontes suplementares não possuem identidade de patch comprovada. Foram
cruzadas com as observações oficiais já registradas; não há fusão automática de
18.3B. TFTraits forneceu os coeficientes AP do escudo de Ivern que estavam como
`?` no TFTCodex e confirmou que o escudo de Diana é apresentado sem escala AP.
Essas referências **não substituem validação empírica**:

- https://tftraits.com/champions/ivern/
- https://tftraits.com/champions/diana/
- https://tftcodex.com/cards.json (hash fixado no manifesto)

Gerar a auditoria, sem executar treino:

```bash
python -m training.ability_audit \
  --output datasets/ability-lab-20261004/audit.json
```

No BigBANANA, `tft habilidades` mostra a cobertura instalada e as pendências por
entrada. `tft simulador` continua mostrando a última execução efetiva; instalar
novas regras não incrementa contadores de treino nem altera resultados antigos.
A conclusão de todas as habilidades segue pendente.

### Mapeamento e revisão online — iteração r5

O mapa regenerável está em `docs/SIMULATOR_RULE_MAP.md` e no JSON correspondente
em `docs/evidence/neural-combat-20261004/iteration-r5/`. Ele enumera as 74 entradas
de campeões/formas, 36 características, 3.444 registros do catálogo global e
cinco formas adicionais. O índice suplementar registra 249 aprimoramentos e
148 Wisps; 25 desses Wisps não mostram preço na referência. Ausência de preço
permanece desconhecida. IDs do catálogo global não comprovam disponibilidade.

Foram lidas online as páginas dos 65 campeões do TFTraits, com atributos visíveis
na seleção de uma estrela, incluindo cinco formas alternativas (70 fichas).
O relatório preserva os conflitos com o catálogo selado. A mana atual da animação
da página **não é mana inicial**. Os tooltips de atributos podem reter valores
de duas estrelas após o clique em uma estrela; a coleta usa o número visível e
registra essa diferença. Fórmulas e balanceamento suplementares não foram
promovidos automaticamente a regras executáveis.

A revisão online de YouTube/Twitch está documentada em `online-video-review.json`:
guia de emblemas de g_ree, vídeo oficial 18.3 da Riot e trecho inicial do novo VOD
2892011367 do Dishsoap. São trechos visuais e transcrições, não VODs integralmente
assistidos nem partidas completas rotuladas. O guia contém um tooltip de emblema
incorreto reconhecido pelo próprio autor. Isso reforça a necessidade de cruzar
vídeo, patch e ID antes de gerar rótulos.

Correções executáveis desta iteração:

- Bloodthirster: limiar 50%, escudo 30% e AD/AP 18; Hand of Justice: AD/AP 18 e
  vampirismo base 15%, preservando o ajuste conforme a vida. Deltas oficiais
  ficam separados do catálogo imutável, com valor anterior, patch e fonte.
- Defender com substituição do bônus de equipe e resistência 115 no patamar 6;
  Caustic com redução renovável e prioridade do efeito mais forte.
- Executioner somente no patamar 2. Sangramento dos patamares 3/4 continua bloqueado.
- Resolução de nomes de campos pelo hash do placeholder, sem inferir semântica:
  97 de 99 campos únicos das características receberam correspondência.

O treino r5 terminou 5.000 combates, 160 épocas e 20.160 passos, em 135,86 s e
185,59 MiB de pico. A validação separada teve 85,84% de acerto contra 51,77% do
baseline majoritário. O conteúdo mudou; esse número não permite comparar
acurácia diretamente com r4. Em 100 decisões com sementes separadas, o planejador
melhorou 8 resultados, manteve 92 e piorou 0 em relação a manter a formação;
p95 da decisão 781,65 ms. Ganho pareado médio 0,16 na escala -1/0/+1, intervalo
bootstrap exploratório 95% [0,06; 0,28]. Isso não é uma taxa de vitória real.

11.409 cenários foram recusados: 8.648 por Greenfather, 2.751 por Blackthorn e
10 por overflow de crítico. Continuam 22 programas de habilidades candidatos,
7 integrados ao combate e 0 validados em replay; 8 características completas
como candidatas, Executioner parcial e 27 handlers de itens. Nenhum novo
instalador foi gerado e os pesos não foram promovidos ao coach.

```bash
PYTHONPATH=apps/hud_mapper:apps/e1_replay:trainer:. .venv/bin/python \
  -m training.simulator_lab.rule_map \
  --output docs/evidence/neural-combat-20261004/iteration-r5/rule-map.json \
  --summary docs/SIMULATOR_RULE_MAP.md \
  --supplemental docs/evidence/neural-combat-20261004/iteration-r5/supplemental-rule-map.json
```

**O inventário do catálogo foi coberto; todas as regras do jogo ainda não.**
Aprimoramentos, Wisps, economia sazonal, loot, fases, invocações e interações
persistentes precisam de implementação e de validação independente. Registrar
uma dependência no mapa não a resolve.
