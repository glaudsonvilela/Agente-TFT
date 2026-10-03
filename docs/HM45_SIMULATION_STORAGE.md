# HM4.5 — pacote, simulação e memória no BigBANANA

## O que o instalador contém hoje

O instalador HM4.5 inclui o aplicativo Windows, captura Rust WGC, prévia,
leitores OCR/HP, modelo L3 de localização de banco/loja em modo diagnóstico,
HUB B4 de posições e ícones candidatos, voz offline e a VM WSL 2 que executa
os leitores. Os eventos, quadros selecionados e telemetria ficam em
`%LOCALAPPDATA%\AgenteTFT-HUD-HM4\sessions`.

Ainda não há identificação validada de todos os campeões/itens, GameState
completo nem simulador TFT calibrado. O worker visual retorna `wait` na
gravação HM4.5. A UI mostra leituras verificáveis; uma instrução de compra
ou equipamento só aparece quando houver identificação e decisão com evidência.
O pacote não deve anunciar 500 partidas simuladas nem aprendizagem online.

## Diagnóstico da sessão de 03/10/2026 às 22:11

O arquivo de diagnóstico `hm4-20261003-221101-505635.rar` registrou
aproximadamente 12 minutos de captura, 1457 frames de origem e 1453 leituras
nativas. A sessão terminou sem erro fatal. O campo
`replay_review_mode=false` desativou o HUB e as orientações; por consequência,
o modelo L3 não foi selecionado (`neural_mode=disabled`,
`model_sha256=null`). A voz também iniciava desligada e só era acionada
quando existia uma orientação. Esses fatos explicam a ausência de leituras
no painel de orientação, de áudio e de inferência neural nessa sessão.

O aplicativo agora inicia a análise de replay e a voz Dii quando o pacote de
voz está disponível no Windows. A voz é aquecida fora da interface antes das
leituras, e a telemetria distingue orientações exibidas, áudio enfileirado,
áudio reproduzido e mensagens descartadas por atraso. O rodapé exibe o modo
de replay, a disponibilidade do modelo e o estado da voz. Isso reativa a
visão neural diagnóstica e as leituras do replay; não cria decisões
estratégicas nem treina pesos automaticamente.

## Primeiro motor de decisão e atualização mensal

A geometria 4×7 do tabuleiro, os nove espaços do banco e as regiões de
HP/ouro pertencem aos perfis em `configs/ui`. O catálogo de campeões e
itens pertence à referência versionada do patch em `knowledge/riot-ddragon`.
O vínculo da partida com o patch fica em `configs/contexts`. Assim, trocar
o conjunto ou patch não altera as coordenadas nem força novo treino dos
leitores de HP e ouro.

O primeiro adaptador do motor liga nomes de loja com confiança de OCR de ao
menos 0,9 a um único ID do catálogo. Ele só sugere comprar a terceira cópia
de uma unidade de uma estrela quando duas cópias próprias tiverem identidade
verificada, a oferta estiver atual e houver ouro confirmado para pagá-la.
Sem esses dados ele registra a razão da abstenção e continua mostrando
leituras factuais. A implementação não libera rolagem, equipamento ou
posicionamento a partir de ícones candidatos.

Nos três pacotes de teste de 03/10, o adaptador vinculou 488, 5636 e 246
observações de ofertas ao catálogo. Todas as decisões continuaram em espera:
as identidades das unidades próprias no tabuleiro/banco não foram
confirmadas. Esses totais incluem ofertas repetidas entre frames; não são
quantidades de campeões diferentes.

Um experimento separado treinou a pequena rede de localização de banco e
loja com 121 imagens das três sessões, 32 recortes de origem e 600 passos.
O modelo experimental exportado tem cerca de 527 kB e inferência p95 de
0,66 ms em CPU sobre a entrada já preparada. No teste sintético, a região
da loja teve erro p95 de 203 px entre propostas aceitas. Em 13 imagens
com nome da loja lido pelo OCR no mesmo frame, houve 13 propostas contra
11 do modelo instalado, usando apenas sobreposição com a geometria fixa
como referência indireta. Não há rótulos independentes de identidade de
campeões, itens ou acerto estratégico. O modelo experimental não foi
promovido ao instalador.

## O que significa 500 caminhos

Uma partida gravada pode fornecer vários **estados observados**. Em cada
momento de decisão confiável, o simulador poderá explorar até 500 futuros
curtos, divididos entre ações legais como guardar ouro, comprar experiência e
rolar um orçamento definido. Cada caminho usa uma semente de aleatoriedade,
uma política de adversários versionada e regras do patch selecionado.

As 500 saídas não são 500 partidas reais nem 500 rótulos para a rede neural.
O melhor caminho isolado pode ter tido sorte. A escolha precisa comparar
distribuições por ação: média, dispersão, risco, custo e intervalo de confiança.
Resultados sintéticos entram na memória como `simulated`; só o replay real
conta como `observed`. O resultado real posterior serve para calibrar e
avaliar o simulador, sem reescrever o passado.

## Execução isolada

O BigBANANA tem quatro CPUs, 15 GiB de RAM e cerca de 9,4 GiB livres em
2026-10-03. O serviço do Agente TFT roda em um quarto contêiner separado dos
três existentes, com limite inicial de 1,5 CPU, 1 GiB de RAM e sem GPU.
O limite é uma política de laboratório; o tempo de 500 caminhos só poderá
ser medido quando o simulador existir. Simular combate e partidas completas
terá custo muito maior que comparar decisões curtas de economia.

## Armazenamento

O contêiner guarda sessões, pedidos e resultados agregados em SQLite no
volume exclusivo `trainer/data/trainer.sqlite3` (WAL e commit durável). Um
reinício preserva os pedidos; tarefas interrompidas ficam marcadas como
falha, sem inventar resultado. Os arquivos de evidência e, futuramente,
trajetórias comprimidas ficam no mesmo volume, fora do banco, com SHA-256.

Cada estado que virar candidato a simulação deverá referenciar:

- sessão e momento da partida, frame de origem e hash da evidência;
- patch, set, regras, catálogo, modelo de visão, simulador e política;
- campos observados, confiança e campos desconhecidos;
- ações candidatas, 500 sementes, limites e resultado por ação;
- ação efetiva observada depois e desfecho real, quando disponíveis.

O servidor recebe estado estruturado e evidência autorizada. Ele não recebe
comandos de mouse/teclado nem precisa de acesso ao desktop. A captura e a
interface continuam locais; um atraso ou falha do servidor não bloqueia o
replay. O canal remoto exige autenticação e transporte protegido; até essa
ligação estar pronta, os dados locais ficam preservados para sincronização.

## Pendências para dicas completas

1. Validar identificação temporal de campeões, estrelas, posição e itens em
   amostras anotadas de mais de uma partida.
2. Criar um GameState com proveniência e `unknown` explícito; reunir regras
   oficiais de cada patch e conjunto em um pacote versionado.
3. Implementar simulador determinístico e bot pool, com testes contra
   probabilidades analíticas e partidas retidas para avaliação.
4. Medir 500 caminhos no BigBANANA, limitar tempo por decisão e guardar
   sementes/saídas; comparar recomendações contra o desfecho real.
5. Treinar e promover uma política apenas depois de avaliação independente.

Esses passos são necessários antes de chamar o instalador de pacote
estratégico completo. O serviço de armazenamento pode ser implantado já,
sem anunciar o simulador como pronto.
