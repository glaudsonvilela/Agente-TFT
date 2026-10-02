# HM2 — mapa do HUD primeiro, captura própria em Rust

HM2 acrescenta captura ao HM1, sem substituir a rede, o OCR ou os dados existentes.
Este protótipo investiga o HUD e coleta material natural. Não declara HUD completa,
precisão TFT, bot operacional, aprovação da Riot ou compatibilidade Vanguard.

## Abrir e selecionar a fonte

Extraia toda a pasta `AgenteTFT-HUD`, mantendo `AgenteTFT-HUD.exe` e `_internal`.
No menu **Fonte de imagens**, escolha **monitor ou janela**. A lista apresenta nome,
adaptador gráfico, resolução e posição dos monitores, inclusive posições negativas.
A opção **Procurar janela TFT / League** apenas sugere títulos compatíveis; não lê a
memória do jogo nem comprova a identidade da janela. Confirme a fonte e clique em
**Iniciar mapeamento**. A seleção sozinha não inicia captura. Ao encerrar/fechar uma
janela capturada não há troca silenciosa para o monitor ou outra janela.

Selecione destino gravável no Windows, cenário e duração. O SSD ext4 do Ubuntu
não é tratado como uma unidade Windows nem formatado. Sem espaço, preserve uma
sessão parcial; não há exclusão automática de históricos. Captura de monitor inclui
qualquer notificação visível naquele monitor. Nenhum áudio, teclado ou clipboard é
registrado. Não desative proteções do Windows ou Vanguard para executar o programa.

Selecione `deployment-candidate.json` com `candidate-model.onnx` da mesma execução
L2/L3. Para treino posterior, mantenha `weights.npz` correspondente ao lado. Os pesos
pessoais não são incluídos no download nem enviados ao GitHub. Referência B1 e S4
EFETIVO continuam opcionais; banco requer B1 para gerar sementes automáticas fracas.

## O que é próprio e o que continua sendo do sistema

`agente-tft-hm-capture.exe` é nosso processo residente Rust: enumeração, ciclo de
captura, buffers D3D11, tamanho válido, conversão BGRA/RGB, timestamps e transporte.
Não usa Ferramenta de Captura/PrintScreen, OBS, BitBlt, FFmpeg por print ou driver
próprio. A obtenção de pixels usa a interface documentada Windows.Graphics.Capture.
A borda de captura do sistema não é escondida. Dependência da API gráfica não é
aprovação da Riot nem um mecanismo de invisibilidade. Sem injeção, leitura de
memória, automação de comandos ou contorno de anticheat.

A API exige Windows com suporte WGC/CreateFreeThreaded/interop de janela/monitor.
Erros de suporte/acesso são reportados; não há backend oculto de reserva. O device
D3D11 tenta hardware e pode usar WARP quando necessário, identificado no relatório.
Isso não garante o mesmo desempenho em computadores diferentes.

## Mapeamento integrado

O mesmo RGB alimenta filas independentes para a rede e os leitores. HM1 é reutilizado:
mapa sobre o frame exato, zoom nos recortes originais, HUD numérico v3, loja e controles
S3 ou S4 escolhido, HP1 baseline e B1 opcional, telemetria e PNGs. A rede é o núcleo
pequeno treinado para **banco e loja**; as outras regiões usam perfis registrados,
não novas classes aprendidas magicamente. Caixas neurais não deslocam ROIs sem
validação. Leituras desconhecidas não viram valores inventados ou rótulos de ausência.

Capturas preservam dimensões físicas; os leitores Match001 ainda exigem1920x1080.
Uma janela com moldura pode ter outras dimensões. Prefira o monitor do jogo em
1920x1080 quando usar esses perfis. Não há correção de escala oculta para fazer um
recorte errado parecer válido. Trocas de tamanho abrem outro segmento geométrico.
Captura BGRA8 é definida como caminho SDR; HDR/cor avançada não estão certificados.

Não há recomendações estratégicas ao vivo. O botão E1 de dicas controladas fica
bloqueado durante uma captura; cenários e replay continuam disponíveis separadamente.
O treinamento só começa após encerrar a coleta, em outro processo; Torch não é
carregado no processo do mapper. As funções existentes de supervisão fraca e
seleção conservadora permanecem. Coleta contínua não significa autoaprendizado
validado ou promoção automática de modelos.

## Arquivos e medidas

Além dos arquivos HM1 (`mapping-events.jsonl`, `roi-observations.jsonl`, `telemetry.jsonl`,
`training-manifest.json`, PNGs, recortes, summary e comparison), a captura registra:

- fonte explicitamente selecionada, fonte nativa e hash do executável;
- WGC SystemRelativeTime, QPC e ponte para o relógio do mapper, com incerteza;
- dimensões, stride, época geométrica e conversão de cor;
- cópia GPU/CPU, conversão RGB, escrita IPC anterior e idade do frame;
- substituições da fila nativa, frames recebidos, amostragem e encerramento.

Uma sessão de captura não recebe um falso hash de vídeo. A separação do treino
utiliza identidade de sessão; sessões diferentes podem pertencer à mesma partida,
portanto não comprovam independência. Previsões, sementes fracas e pixels originais
permanecem separados. Um PNG sem perdas conserva o RGB recebido; não prova captura
HDR sem alteração ou sem compressão que já existisse no conteúdo de origem.

## Testes e limites

A suíte nativa tem testes de stride, buffer, orçamento e consentimento. O teste
Windows real captura uma janela sintética própria, verifica cores, timestamps,
seleção e redimensionamento, e captura um monitor disponível. Não testa TFT nem
Vanguard. Uma fixture de dois monitores testa seleção/identidade, não substitui um
ensaio com dois monitores físicos. O relatório deve dizer quantos existiam no runner.

O CI HM2 também precisa executar captura -> ONNX -> leitores -> PNG/telemetria e o
EXE empacotado. Testar uma janela sintética menor não certifica OCR em TFT1920x1080;
esses leitores são exercitados separadamente pelos testes HM1 existentes. A
latência observada no CI não é previsão de latência no PC do usuário.

Os erros geométricos e dados sazonais pendentes não são resolvidos só por capturar
novos frames. Próximo material a analisar: `comparison.txt` e o manifesto natural,
com fontes/filas/cobertura antes de qualquer novo treino ou perfil ativado.
