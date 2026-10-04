# Simulação e treinamento da política

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
