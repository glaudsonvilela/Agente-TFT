# E1 — primeiro laboratório executável de replay e atraso

E1 0.1.0 é uma fatia vertical experimental, NÃO o Agente TFT completo.
Só aceita vídeo local encerrado ou cenários controlados. Não captura janelas,
não injeta código, não lê memória de jogos, não opera teclado/mouse e não dá
dicas de partida oficial ao vivo. C1 Windows.Graphics.Capture permanece pendente.

## Uso no Windows

Extraia toda a pasta do artefato `AgenteTFT-E1-Windows-x64`, abra
`AgenteTFT-E1.exe`, escolha uma pasta de resultados com espaço e inicie.
O pacote portable inclui Python privado, worker Rust, FFmpeg e Tesseract; não
instala nem modifica o Python, Rust ou outros ambientes da máquina. Não separe
os arquivos `_internal` do executável. Não é assinado digitalmente; nenhum
procedimento para desabilitar Defender/SmartScreen/Vanguard faz parte da entrega.
O SSD ext4 do Ubuntu não é presumido como destino nativo gravável do Windows.

Duas trilhas:

* **Cenários controlados**: relógio sintético explícito, GameState/fatos de laboratório
  -> OpportunityEngine e DecisionCore EXISTENTES -> texto determinístico -> UI.
  Compra/subida/economia/roll são decisões do motor sobre fatos fornecidos; não
  percepção da tela nem simulador de combate. Os fatos fornecidos NÃO são medidas
  feitas por avaliadores ainda não ligados.
* **Vídeo local**: FFmpeg residente -> pixels RGB + PTS -> leitores HUD v3,
  cinco cartas e controles S3 congelados -> estado parcial -> engine em fase
  desconhecida -> abstenção concreta -> UI. Não inventa fase, identidade ou HP para
  preencher dicas. S4 segue a referência de projeto: selecione seu perfil efetivo
  de controles S4 para reutilizá-lo; o preset portátil não se anuncia como S4.

Opcionalmente escolha `deployment-candidate.json` e o ONNX ao lado (L2/L3), e o
JPEG de referência B1. A rede roda sobre o mesmo RGB processado, como observadora:
NÃO desloca ROIs ou treina. B1 executa os mesmos algoritmos de barras/assinaturas;
NÃO prova unidades/células. Não acompanha contas nem reconhece HP. Sem opcionais,
o relatório marca tais componentes `not_connected`, não tempo zero.

A trilha visual é válida para os perfis Match001 1920x1080: outra resolução é
registrada como incompatível, sem escala implícita. Os gráficos do jogo não são
compilados no executável. Imagens pessoais e pesos não vão para o GitHub.

## O que está realmente integrado

Uma fonte com relógio independente do consumidor, preview, trabalhador residente
Rust (algoritmos reutilizados por módulos/path e crates), OCR real, dados por frame,
OpportunityEngine/DecisionCore reais e painel. Texto é um formatador determinístico
mínimo do E1, não execução do coach/LLM. Somente a trilha controlada produz dicas
acionáveis neste marco; a visual mostra valores lidos e bloqueios reais.

Não confundir esse estado parcial com StateFusion temporal ligado ou GameState
oficial atualizado. Não há estratégias completas, avaliação de combate, treinamento,
coletor Windows, captura compartilhada com jogo, modelo promovido ou assistência
aprovada pela Riot. Sucesso de build/CI não comprova acurácia TFT ou compatibilidade
Vanguard. L1/L2/L3 e seus bloqueios não são alterados.

## Relógios e filas

FFmpeg `showinfo` fornece PTS; sem filtro fps, interpolação ou futuro usado como
fato. O produtor libera frames no ritmo 1x e não espera OCR. Há uma vaga pendente
por consumidor substituível e por preview/UI: supersessões são contadas; não são
recuperações de eventos. Fonte atrasada permanece identificada pelo PTS original.
Uma sessão = uma época; sem seek/pausa nesta versão, encerrar e abrir outra.

Frames já em execução terminam ou atingem timeout. Aos 12 segundos, o supervisor
encerra apenas a árvore do worker que iniciou. Cancelamento para a mesma árvore,
não encerra o jogo ou outros aplicativos. FIFO acumulada não vira latência invisível.
Stress opcional adiciona 600 ms identificados como espera injetada, NUNCA como
inferência/LLM real. Não simula automaticamente a carga CPU/GPU de uma partida.

Spans nativos são durações/offsets no worker. O relógio causal de entrada/saída/UI
é `perf_counter_ns` do MESMO processo Python; não se subtraem relógios incompatíveis.
No Windows, este mecanismo utiliza o contador de desempenho do sistema. `ui_applied`
é confirmação da aplicação Tk, não scanout físico do monitor. Teste headless NÃO
preenche as métricas de UI. A dica expira após 2 s desde a liberação programada da
fonte; aparece como expirada, inclusive se o usuário não recebe uma leitura nova.

## Relatório automático

Cada execução cria uma pasta exclusiva com `trace.jsonl`, `native-stderr.log`,
`summary.json`, `comparison.txt` e selo `COMPLETE.json` ou `PARTIAL.json`.
Metadados de fonte, configurações, origem de resultados e capacidades são explícitos.
São medidos atraso da fonte, fila, trabalho nativo + IPC, etapas do worker, texto,
até resposta pronta e até aplicação Tk. Percentis são calculados por trace; não
somamos percentis de componentes. O ranking de etapas é custo observado, NÃO
atribuição causal completa de cada pico. Preparação ONNX e inferência são separadas.

O arquivo não é benchmark do futuro produto completo. Quadro sem dados que termina
em Wait não conta como recomendação estratégica bem-sucedida. CPU/GPU, fotodiodo,
custo de futuros módulos e taxa de acerto continuam não medidos. O custo de
telemetria é contabilizado separadamente (enqueue e escrita assíncrona), sem alegar
ensaio rigoroso com instrumentação desligada. Sem upload de conteúdo por padrão.

## Reprodução pelo código

```bash
cargo build --release --manifest-path tools/e1-native/Cargo.toml
python -m pip install -r apps/e1_replay/requirements.txt
python apps/e1_replay/AgenteTFT_E1.py
```

Use o ambiente existente adequado e diretórios no SSD; não é necessário reinstalar
Torch/DINO e nenhum deles é importado. FFmpeg, ffprobe e Tesseract devem estar no
PATH no modo fonte. O Windows portable já os contém. Para CI/reprodução:

```bash
PYTHONPATH=apps/e1_replay python -m unittest discover -s apps/e1_replay/tests -v
PYTHONPATH=apps/e1_replay python apps/e1_replay/tests/native_smoke.py --output NEW-test
```

O teste nativo exige ferramentas reais; o unitário que usa WorkerFixture é teste
de agendamento explicitamente simulado. Não reportá-lo como teste da rede/engine.
Suítes antigas continuam; módulos de percepção não são reescritos no E1.

## Próximo trabalho ligado

Usar os traces para comparar custo e espera da loja/HUD, ampliar extração de fatos
sem preencher dados falsos e conectar gradualmente fusão temporal/HP/modelo. Depois,
captura Windows C1 e timestamps nativos, recursos/visibilidade/captura do player de
replay e revisão de compatibilidade. O problema de oclusão cruzada do gerador L3
permanece aberto; a criação do painel não o corrige. Os22 apontamentos antigos não
foram declarados resolvidos. Estado de build, testes e PR deve ser conferido remoto.
