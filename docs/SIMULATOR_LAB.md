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
