# Agente TFT — revisão de replay na tela (HM4 Auto)

HM4 mantém o motor de captura/leitura do HM3 e simplifica a experiência para o teste no Windows.

## Fluxo

1. Abra o HM4.
2. Abra no Windows um vídeo de uma partida **já encerrada**, em tela cheia
   16:9, sem barras ou controles do player sobre a HUD. Não é necessário
   fornecer o caminho do vídeo ao HM4.
3. Clique em **Escolher monitor/janela**, selecione a janela do player ou o
   monitor que exibe o vídeo e marque **Revisar vídeo encerrado (HUB + dicas)**.
4. Clique em **INICIAR**. Quando o tabuleiro do próprio jogador aparecer no
   vídeo, clique em **Calibrar tabuleiro**. Uma cena errada pode ser substituída
   por nova calibração manual.
5. Consulte **Mapa neural + geometria**, **Tabuleiro / itens**, **Performance**
   e as dicas de revisão. Cada resultado mostra o frame de origem. A dica exibe
   uma estimativa do tempo da captura até a atualização da UI, sem alegar medir
   o atraso físico do monitor ou do player de vídeo.
6. Clique em **ENCERRAR** para selar a sessão. O diretório da sessão contém
   `board-hub-observations.jsonl`, `replay-tips.jsonl` e `summary.json`.

Não há seleção manual de JSON/ONNX nem pasta de saída no fluxo HM4.

## Automação

- A resolução vem diretamente da fonte capturada.
- A pasta de sessão é criada automaticamente em `%LOCALAPPDATA%\AgenteTFT-HUD-HM4\sessions`.
- O instalador de revisão inclui o par L3 `deployment-candidate.json` +
  `candidate-model.onnx`; o HM4 também procura modelos compatíveis em locais
  padrão do aplicativo/usuário.
- Se encontrar um modelo L2/L3 compatível, ativa o observador neural em modo
  diagnóstico, independente do leitor do tabuleiro.
- Se não encontrar, o aplicativo **não bloqueia**: captura, telemetria, geometria registrada e leitores nativos continuam ativos. A parte neural fica explicitamente desativada.
- A entrada 16:9 pode ser normalizada para os leitores 1920×1080 como descrito
  em HM4.1. Outra proporção é recusada.

## Segurança do escopo

A captura continua sendo o processo Rust residente sobre Windows.Graphics.Capture/D3D11. HM4 não usa memória do jogo, injeção, automação de input, driver próprio ou bypass de anti-cheat.

## Entrega

O build Windows produz:

- `AgenteTFT-HUD-HM4-Auto-Windows-x64.zip`
- `AgenteTFT-HUD-HM4-Auto-Setup.exe`
- `HM4_PACKAGE_REPORT.json`

O pacote de revisão inclui os pesos L3 e 156 ícones oficiais do escopo visual
`TFTSet18/` para o catálogo B4 versionado. Não inclui PyTorch, FFmpeg, arquivo
de replay ou treinador. A rede L3 localiza aproximadamente banco e loja; não
identifica campeões nem itens e não aprende durante a sessão. O B4 registra
células e ícones **candidatos**, com identidades nulas. Dicas de revisão são
leituras de economia baseadas nos números observados. Ações de compra/equipamento
exigem identidade verificada, evidência fresca e confiança explícita do motor;
ícones candidatos sozinhos não geram dicas de equipar. Sem ouro observado, a
leitura se abstém. O modo de dicas só é habilitado quando o
usuário declara que a fonte é um vídeo de partida encerrada.

## HM4.5 — narração local opcional

No instalador HM4.5, marque **Narrar orientações** e escolha a voz em
**Voz** e use **Testar voz** antes de iniciar o replay. As duas vozes em
português brasileiro já existentes continuam disponíveis; **Dii**, uma voz
feminina brasileira, é a opção inicial. A síntese ocorre em uma
thread separada, com um núcleo de CPU, sem serviço de nuvem nem voz do sistema.
Mensagens antigas são descartadas; a dica escrita aparece mesmo se a fala
estiver desligada ou demorar. A aba **Performance** mostra o tempo de geração
e um eventual erro de voz.

Os modelos de voz vêm dos pacotes `vits-piper-pt_BR-{cadu,faber}-medium-int8`
e `vits-piper-pt_BR-dii-high-int8`
da release `tts-models` do projeto `k2-fsa/sherpa-onnx`, verificados por SHA-256
no build. A licença do motor e os cartões dos modelos acompanham o instalador.
O pacote Dii é para uso não comercial de laboratório, conforme seu `README.md`.


## HM4.1 — normalização conservadora dos leitores

HM4 pode derivar uma cópia temporária 1920×1080 para os leitores congelados quando a captura tem proporção 16:9. O frame capturado original continua sendo a evidência salva. A derivação usa RGB + Lanczos, registra tamanho de origem, tamanho canônico, fatores de escala e método, e projeta as caixas lidas de volta para as coordenadas do frame original.

Fontes que não são compatíveis com 16:9 continuam recusadas; não há stretching silencioso nem tentativa de adivinhar letterbox.

Contadores novos:
- `reader_normalized_runs`
- `reader_resolution_skipped`
- `reader_input_transform` em cada observação de ROI.

## Auditor de sessão

Para resumir uma sessão ou ZIP sem executar OCR/modelo:

```powershell
python scripts/audit_hm4_session.py "C:\caminho\teste.zip" --output hm4-session-audit.json
```

O relatório agrega resolução capturada, ativação neural, execuções nativas, normalizações, status por região, valores observados, campos stage/gold/level/xp/HP e quantidade de amostras ainda sem rótulo.


## HM4.2 — caminho rápido e L2 shadow

Estado validado no Windows CI antes deste pacote:

- HUD numérico (stage/gold/level/xp) executa em paralelo, preservando políticas/thresholds existentes.
- HP roda em processo independente e em paralelo ao caminho principal.
- Cache exato por bytes de ROI para HUD; cache exato dos pixels realmente consumidos por loja/controles.
- HM4 usa 2 Hz como cadência padrão dos leitores.
- Loja/controles têm cadência separada de 2 s; entre leituras, o último resultado é reapresentado com idade e provenance explícitas, sem ser marcado como fresco.
- O L2 espacial é somente shadow diagnóstico: não escreve GameState, não alimenta leitores, não é ground truth e não pode virar training label.
- summary.json e audit_hm4_session.py registram explicitamente o modo neural e as permissões bloqueadas.

Benchmark determinístico do runtime em GitHub Actions, 1920x1080 (run 37079664767):

- primeiro frame completo/fresco: 468.12 ms native; 474.34 ms wall;
- segundo frame byte-idêntico/cacheado: 0.57 ms native; 6.86 ms wall;
- frame alterado com HUD rápido e loja fora da cadência: 477.30 ms native; 483.38 ms wall;
- frame alterado com HUD + HP em paralelo: 503.28 ms wall;
- reapresentação da loja fora da cadência: aproximadamente 0.03 ms no benchmark.

Esses números são benchmark do runner CI, não promessa de latência do PC real. A comparação de campo deve ser feita numa nova captura natural usando o mesmo formato de relatório da sessão anterior.


## HM4.2 — selo final de regressão

Antes deste pacote final, o fast path também validou:

- comparação automática old-vs-new de auditorias HM4, preservando a sessão anterior como baseline;
- guard automático contra regressão da rota rápida dos leitores;
- nenhuma alteração de threshold, ground truth, treino ou promoção do L2;
- L2 permanece shadow diagnóstico somente.

Este commit existe apenas para executar o full package gate sobre o mesmo código já aprovado no fast path.


## HM4.3 — HP assíncrono e encerramento gracioso

O teste natural HM4.2 de 2026-10-02 confirmou queda relevante de latência do caminho de leitores (p50 ~6241 ms → ~2104 ms; p95 ~9108 ms → ~4930 ms), mas mostrou que o HP1 síncrono ainda bloqueava a publicação de cada ciclo: p50 próprio ~1074 ms e p95 ~2436 ms. O relatório agregado está em `docs/HM4_2_FIELD_TEST_20261002.md`.

HM4.3 mantém os leitores e thresholds congelados e muda apenas o agendamento/proveniência:

- HP1 passa a uma fila independente latest-only de 1 Hz.
- O HUD/loja não espera mais o OCR de HP para publicar seu próprio resultado.
- Um resultado de HP só pode acompanhar um frame se for causal (nunca de um frame futuro) e pertencer ao mesmo segmento geométrico.
- HP com mais de 2 s é `async_stale`: o último diagnóstico é preservado na proveniência, mas o valor numérico não é apresentado como atual.
- Métricas de HP (fila, source→result e tempo nativo) são reportadas separadamente.
- O caminho HM3 preserva o comportamento same-frame anterior.
- Clicar **ENCERRAR** agora é parada graciosa: se não houve erro, a sessão é selada como completa com `stopped_by_user=true`; erros e timeouts continuam parciais.

Não há mudança de threshold, ground truth, GameState, permissão de training label, promoção de perfil ou ativação silenciosa do L2.


## HM4.3 — gate de pacote final

Antes do pacote final, o head `e3306679a0bbd2bc011436f7a1594c058c720205` foi validado pelos quatro gates relevantes:

- CI #562: success;
- HUD Mapper HM2 #22: success, incluindo Windows portátil e WGC;
- HUD Mapper HM3 Runtime #15: success após retry isolado do smoke WGC do runner, incluindo portátil e instalado;
- HUD Mapper HM4 Auto #44: success, incluindo contratos, auditor, comparador, Rust readers e benchmark rápido.

O retry HM3 foi necessário porque a primeira tentativa do runner Windows retornou `invalid ContentSize or unexpected pixel format`; a repetição isolada passou sem alteração de produção. Este registro não converte instabilidade do runner em correção de código.

O commit deste trecho existe somente para acionar o full-package gate do HM4.3 sobre o mesmo código já aprovado.


## HM4.4 — gate final do OCR Hub

Head técnico validado antes do pacote final: `a8c955b05670eb6bcaa4ec9cd5bfec814666bdd1`.

Gates verdes:
- CI #597;
- HUD Mapper HM2 #52, incluindo Linux, Windows portátil, WGC, integração e executável real;
- HUD Mapper HM3 Runtime #45, incluindo portátil e runtime instalado;
- HUD media #61;
- E1 Replay Lab #29;
- HUD Mapper HM4 Auto #78.

Resultados do OCR Hub no Windows CI:
- CLI HUD-only: ~292.60 ms;
- residente HUD-only: ~16.84 ms;
- speedup A/B: ~17.37×;
- 4 startups × 8 frames = 32 frames do worker residente concluídos;
- paridade numérica: stage/gold/level/xp com texto e confiança iguais no gate sintético;
- paridade de texto espacial: igualdade de palavras/caixas/confiança;
- atlas de loja: speedup ~7.2×–7.3× no gate sintético com paridade.

HM4 Auto usa `AGENTE_TFT_RESIDENT_OCR=auto`: tenta OCR residente no Windows e mantém fallback explícito para o backend CLI se a inicialização falhar. HM2/HM3 preservam seus contratos anteriores.

O commit deste trecho contém `[full]` somente para acionar o empacotamento e os smokes finais sobre o mesmo código já aprovado.
