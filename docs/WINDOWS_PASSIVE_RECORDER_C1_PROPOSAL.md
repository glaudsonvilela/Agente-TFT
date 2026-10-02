# C1 — proposta de coletor passivo de sessões no Windows

## Estado e pedido

Documento de desenho, não implementação nem executável. Base consultada:
`cc80d6117385b5de42a592e9a1ab976499887e0d`.

O usuário propôs coletar a própria tela durante partidas no Windows e gerar
arquivos reutilizáveis pelos leitores existentes, em vez de continuar dependendo
principalmente dos 40 JPEGs e de composições artificiais do Match001. Também
manifestou preocupação com falsos positivos do anticheat. Essa preocupação não
é evidência de bloqueio real da captura: não foi fornecida uma mensagem desse tipo.

Direção recomendada: primeiro gravador passivo e transparente; enriquecimento
com visão/OCR e treinamento APÓS a sessão. Não ativar assistência estratégica
na partida para demonstrar o gravador. Não ocultar processos, simular outro
programa, contornar bloqueios ou substituir captura documentada por acesso à
memória do jogo. A escolha proposta de Windows.Graphics.Capture não deve ser
confundida com aprovação da Riot; depende de validação de compatibilidade e de
concordância com esse método documentado, em vez de uma solução de evasão.

## Fontes oficiais consultadas

1. Microsoft, captura de tela:
   https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture
   Documenta seletor de janela/tela, indicação visual da captura, ContentSize,
   SystemRelativeTime, buffers, redimensionamento e cuidados com HDR.
2. Microsoft, Desktop Duplication:
   https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api
   API documentada alternativa de captura de desktop. Não é um mecanismo de
   invisibilidade e não será fallback para contornar uma recusa de acesso.
3. Microsoft, pixels físicos e unidades independentes de resolução:
   https://learn.microsoft.com/en-us/windows/win32/direct2d/direct2d-and-high-dpi
4. Riot, políticas específicas de TFT:
   https://developer.riotgames.com/docs/tft
   Incentiva análise pós-partida e restringe assistência dinâmica e rastreamento
   de adversários durante o jogo. Produtos que atendem jogadores precisam ser
   registrados, inclusive sem uso de uma API oficial.
5. Riot, aplicações de terceiros:
   https://support.riotgames.com/en-us/riot/events/third-party-applications
   A Riot não divulga os detalhes de detecção nem fornece uma lista exaustiva de
   ferramentas seguras. Não existe garantia de ausência de bloqueio para este
   protótipo. API da Microsoft não equivale a API/aprovação da Riot.
6. Riot, comunicado de 29/09/2026:
   https://support.riotgames.com/en-us/riot/performance/game-memory-access-removed-for-third-party-apps
   Anuncia bloqueio de acesso à memória por aplicações desconhecidas a partir de
   06/10/2026, com transição para ferramentas conhecidas/aprovadas até abril/2027.
   O comunicado não deve ser interpretado como autorização de visão/OCR ao vivo.

São fontes de requisitos, não confirmação de que um C1 foi testado ou aprovado.
Antes de disponibilizar uma integração em partidas, descrever o fluxo concreto
no Developer Portal e esclarecer o enquadramento do coletor/extração pós-partida.
Não desabilitar Vanguard, Defender ou controles do Windows para fazer o teste.

## MVP proposto

Nome de trabalho: `AgenteTFT-Coletor.exe` (arquivo ainda não gerado).

- Seleção explícita da janela/tela pelo usuário, prévia e controles Iniciar,
  Pausar e Encerrar. Indicação de gravação preservada; nenhuma captura oculta.
- Preferir somente a janela selecionada; sem microfone, áudio, credenciais,
  clipboard ou registro de teclas por padrão. Não trocar silenciosamente para
  captura de desktop ao minimizar/fechar a janela ou perder o acesso.
- Executar como usuário normal. Sem driver próprio, injeção no processo do jogo,
  leitura de memória, captura de tráfego do jogo, automação de teclado/mouse,
  manipulação de anticheat ou mecanismo para disfarçar o programa.
- Durante a partida, UI mostra somente estado do gravador: tempo, tamanho,
  frames recebidos/salvos/perdidos e erros. Sem dicas de compra/roll, scouts,
  grades recomendadas, contagem de adversários ou exposição de estado estratégico.
- Registro audiovisual sem áudio, segmentado e limitado, mais timestamps e
  metadados. Proposta inicial: 30 fps quando suportado; 60 fps opcional somente
  depois de medir custo. Frames reais e perdas são registrados, não inventados
  para aparentar taxa constante. Não executar OCR nessa frequência.
- Preservar amostras nativas sem perdas e contexto temporal com orçamento
  explícito. Não coletar exclusivamente quando o modelo atual tiver dúvida:
  amostragem periódica neutra evita depender dos seus próprios erros.
- Fechar a sessão explicitamente antes do enriquecimento inicial. Os módulos
  de percepção existentes geram observações depois, sobre a gravação; esses
  resultados continuam como hipóteses com origem, não rótulos verdadeiros.
- Não carregar PyTorch, treinador, Grounding DINO, recomendador ou atualizador
  de pesos durante a coleta. Execução neural diagnóstica ao vivo é outra
  capacidade e fica pendente de revisão própria, não entra disfarçada no C1.

## Pontos de integração conferidos no código

`rust/crates/capture-core/src/lib.rs` já define `CaptureSource`, `FrameEnvelope`,
formatos RGB/RGBA/BGRA, stride e identidades de frame/fonte. O enum possui
`WindowsTft`; isso não implementa por si só um capturador Windows. O backend deve
alimentar esse contrato, sem tornar todos os leitores responsáveis por capturar.

`rust/crates/capture-replay/src/lib.rs` oferece `ReplayVideoSource`. No caminho
inspecionado, usa reamostragem `fps=...` e timestamp calculado pelo índice e taxa
alvo. Esse relógio de replay NÃO será apresentado como horário nativo da captura.
O arquivo C1 deve conservar timestamp monotônico real e sua relação com o PTS
codificado; adaptação de replay precisa preservar lacunas e duplicações.

U1, L1, L2 e L3 continuam com identidades separadas. Não carregar pesos pelo nome
parecido nem tornar o coletor um motivo para promover um mapa não validado.

## Contrato de pixels e tempo

Registrar e testar juntos, antes de treinar sobre dados novos:

1. Dimensões físicas e ContentSize da captura; não confundir tamanho alocado da
   superfície com área válida. Mudança de tamanho abre outro segmento de geometria.
2. Espaços explícitos: tela, janela, área capturada e tensor da rede. Guardar
   matriz de recorte/escala e sua inversa; não reutilizar coordenadas do desktop
   numa captura sem as bordas da janela.
3. DPI, escala da UI quando conhecida, canal RGB/BGRA, stride e orientação.
   Não duplicar escala do sistema nem interpretar padding de linha como pixels.
4. Política de SDR/HDR e cursor. Nunca normalizar cor silenciosamente ou usar
   dados indefinidos fora de ContentSize como entrada da rede.
5. `session_id`, `frame_id`, timestamp monotônico, base temporal/frequência e
   número do segmento. Hora civil é metadado, não substitui o relógio monotônico.
6. Toda previsão referencia um frame salvo e uma versão do leitor. Resultado
   atrasado não atualiza outro frame; cena preta, minimizada ou indisponível não
   é automaticamente um banco vazio.

Esses cuidados atacam potenciais deslocamentos de pixels na entrada. Não provam
que a rede passou a localizar corretamente os painéis nem as células do chão.

## Armazenamento e dados gerados

Estrutura proposta, ainda não emitida por um executável:

```
session-<id>/
  session.json           # origem, consentimento, versão, geometria e limites
  segments/              # gravação original segmentada
  samples/               # amostras nativas selecionadas com política registrada
  frames.jsonl           # timestamps, arquivo/PTS, geometria, perdas
  capture-metrics.json   # custo, filas, uso de disco e interrupções
  derived/<reader-hash>/  # somente após sessão: previsões de cada leitor
  checksums.json         # integridade dos segmentos concluídos
```

Originais e previsões separados. Sem `ground_truth` fabricado a partir de
confiança alta, concordância temporal ou comparação com B1. Componente ausente
fica não executado; falha registrada, nunca valor inventado para completar JSON.

Destino escolhido explicitamente entre locais que o Windows realmente consegue
usar, com teste de escrita e espaço. O SSD SHERLOCK_SSD foi descrito como ext4
no Ubuntu: não presumir que tem uma letra de unidade no Windows, formatá-lo,
instalar driver de filesystem ou recorrer a caminhos Linux como se fossem nativos.
Não usar a partição cheia do sistema como fallback. Sem upload automático de
imagens ou pesos para GitHub; publicação apenas de código e evidência resumida
aprovada, removendo dados pessoais.

## Orçamento e gargalos a medir

- Captura assíncrona, sem bloquear UI nem jogo com compressão, hash ou inferência.
- Uma fonte de frames compartilhada; respeitar o ciclo de vida dos buffers da
  API. Não reutilizar uma superfície devolvida ao pool.
- Filas de capacidade limitada e contagem explícita de descarte/atraso. Sobrecarga
  reduz trabalho opcional; falta de espaço encerra com estado parcial, sem apagar
  sessões anteriores ou fingir conclusão.
- Preservar qualidade suficiente de texto. Vídeo comprimido não deve ser tratado
  como cópia pixel a pixel; ancorar verificações geométricas em amostras sem perdas.
- Medir captura, cópia GPU/CPU, conversão/resize, codificação, escrita, memória e
  percentis end-to-end com trabalho equivalente. Não extrapolar 1,57 ms de ONNX
  Linux para latência do aplicativo Windows.

## Aprendizado e próxima sequência

Sessões naturais passam a ser o principal conjunto de desenvolvimento. Os 40
frames antigos continuam como regressão; transformações sintéticas ficam como
complemento e testes de geometria. Separar treino/validação/teste por partida,
não por frames vizinhos. Repetição temporal não cria amostras independentes.

O defeito de oclusão cruzada do gerador L3 NÃO desaparece por adicionar vídeos.
Corrigir a supervisão por camadas/pontos antes de reutilizar composições no treino.
Não exigir localização de canto encoberto como observação exata. Vídeos reais
melhoram o material disponível, mas não fornecem automaticamente coordenadas ou
identidades corretas. Aquisição contínua não significa pesos atualizados ao vivo.

Ordem proposta:
1. Concordar com captura documentada/transparente e esclarecer o uso com a Riot.
2. Implementar e compilar C1 num runner Windows; artefato, hashes e testes.
3. Validar captura/resize/cor/timestamps sobre uma aplicação de teste e um replay
   conhecido, sem jogo conectado, antes de uma sessão com Vanguard.
4. Coletar sessões próprias e enriquecer após a partida com os módulos existentes.
5. Corrigir supervisão sintética e comparar candidatas em partidas separadas,
   antes de qualquer promoção ou conexão aos leitores.

Publicação deste documento: nenhuma compilação Windows, execução de testes,
assinatura digital, instalação, sessão de captura, aprovação da Riot, novo
training ou alteração de runtime realizada. Não usar esta proposta para afirmar
que o executável já existe, é indetectável ou é seguro contra toda sanção.
