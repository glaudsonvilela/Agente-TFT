# HUD Mapper HM1 — o HUD é o objetivo principal

Evolução aditiva do E1 (`14bc6c07f3a03d4f6e9edbf392f5a22aeb697796`).
O usuário pediu que o executável sirva principalmente a mapear a interface,
coletar cenários reais e preparar/treinar candidatas. Desempenho e motor continuam
junto, mas não substituem esse objetivo. Esta versão usa gravações locais já
encerradas; não captura a tela do jogo e não contém evasão/automação de entradas.

## Executável e primeiro uso

Extrair TODA a pasta e abrir `AgenteTFT-HUD.exe`, mantendo `_internal` ao lado.
Não instalar Python/Rust/Tesseract no computador do usuário. O pacote inclui um
ambiente privado, ONNX Runtime, os executáveis existentes do E1, FFmpeg, o leitor
HP1 e o treinador CPU. PyTorch está disponível no pacote para treino separado,
mas NÃO é importado no processo que observa a gravação. Não inclui DINO/GPU/CUDA,
fontes, vídeos ou pesos pessoais. Sem assinatura digital ou certificação Riot.
Não desabilitar proteções do Windows para abrir o protótipo.

Escolher:
- vídeo encerrado e pasta Windows gravável com espaço;
- `deployment-candidate.json` do L2/L3, com `candidate-model.onnx` ao lado;
- opcionalmente o JPEG B1 do banco vazio e o perfil EFETIVO S4 dos controles.

Copiar também `weights.npz` da MESMA execução para possibilitar treinamento.
Sem modelo não há início do modo neural: não trocamos por rede aleatória ou
`not_connected` silencioso. O caminho antigo de cenários do motor segue disponível
em janela separada. Dados de cenários não viram observações da gravação.

## Tela e dados

A tela principal alterna entre o frame do mapa neural e o frame dos leitores.
Retângulos NÃO são aplicados ao frame mais recente quando foram calculados em
outro frame. Congelar inspeção não para a coleta; o frame inspecionado permanece
identificado. Selecionar uma linha abre o recorte da mesma imagem, com origem,
valor/estado e coordenadas. Caixas inválidas não são corrigidas por clipping.

- Rede real L2/L3: banco/loja, saída normalized_tlbr, contrato e hash conferidos.
  Ainda são propostas grosseiras. A rede NÃO foi magicamente treinada para stage,
  HP, itens e todo o tabuleiro. Essas limitações aparecem na tabela.
- HUD textual: estágio, ouro, nível e XP via leitor v3 existente. A recuperação
  v4 de estágio não foi reimplementada nem é anunciada aqui.
- Loja: cinco cartas, nomes/preços e controles; preset S3 ou perfil efetivo S4
  selecionado explicitamente. O programa não chama S3 de S4.
- HP: leitor baseline HP1 existente, em processo residente próprio. Mantém
  tentativas/retângulo/estado e não transforma o badge em identidade de conta.
  A candidata HP text-fit em quarentena NÃO é ativada.
- B1 opcional: barras, comparação de referência, banco e pontos-guia. Esses
  pontos vêm da projeção configurada, NÃO são landmarks do chão observados.
  Correspondência de arena não prova ocupação, e a rede não move os recortes.
- Identidade/estrelas/itens/augments/atributos não concluídos ficam explícitos.

`mapping-events.jsonl` contém previsões da rede. `roi-observations.jsonl` contém
leituras e tentativas reais do worker. Ambos preservam frame/PTS. `samples/` guarda
PNGs nativos sem perda, `crops/` recortes com coordenadas e hashes; não fotos do
preview reduzido. Há seleção periódica neutra independente da rede, mais amostras
dos leitores/rede com orçamento temporal. Nunca se chama ausência de detecção de
painel oculto ou rótulo correto. Dados desconhecidos continuam sem `targets`.

`training-manifest.json`, `summary.json`, `comparison.txt`, métricas de escrita e
selo COMPLETE/PARTIAL são gerados automaticamente. Não há upload de imagens para
o GitHub. Índices são por sessão e por hash do vídeo, não apenas pelo nome da pasta.

## Treino após a sessão — real, mas explicitamente experimental

A aba Dados e treinamento permite preparar sementes e iniciar uma candidata em
OUTRO processo. Não roda treino enquanto a sessão está ativa e não troca os pesos.
Exige NPZ/ONNX da mesma execução: uma inferência pareada verifica a equivalência.

As sementes automáticas são **fracas**, não gabarito. A loja só é selecionada
quando os localizadores visuais existentes aceitam seu painel; o banco exige a
referência B1 e a correspondência da arena. Isso corrobora um perfil cadastrado,
mas não prova todos os cantos nem a visibilidade de cada painel. Esses limites
fazem parte do JSON e do consentimento antes do treino. A rede não se auto-rotula.

Precisam existir pelo menos 24 imagens distintas e 12 sementes por painel.
Sem elas, o treino recusa a execução e preserva os casos desconhecidos. Não
preenche alvos para fazer o treinamento passar. Outras sessões podem ser
adicionadas. Com pelo menos três vídeos, a separação é por hash completo de vídeo;
com menos, usa divisão cronológica declarada de desenvolvimento, NÃO nova partida
independente. Dados repetidos não se tornam amostras independentes.

O treinador reaproveita o núcleo L2 de 27.726 parâmetros. A cópia desse pacote
vem da árvore Git congelada `fe4743f10fa7e617a1ad151e238c54aa90286c30`, sem modificar
seus fontes. O adaptador HM1 usa nós com alcance 0..1, alvos bilineares, renderização
nativa seguida de um resize e coberturas aplicadas a TODOS os pontos afetados.
Não reutiliza o renderer defeituoso L3 de colagens com oclusão cruzada.

Otimização limitada, seleção por validação (não teste), comparação pareada
pai/candidata, exportação ONNX e paridade real. Erros são contra referências
fracas transformadas, NÃO precisão natural certificada. Arquivos inicial/final/
último passo ficam separados. Um treino que não melhora pode manter o ponto
inicial selecionado; isso não apaga que houve otimização nem simula uma melhora.

A candidata exige avaliação posterior e seleção explícita. Nenhum perfil ativo,
GameState, catalogação sazonal ou registro de quarentena é alterado. Aprendizado
contínuo autônomo e mapa completo de HUD continuam não estabelecidos.

## Caminho de desempenho

Fonte independente a 1x -> filas substituíveis para rede e leitores -> resultados
por frame. A rede não espera o OCR. E1 nativo e HP1 recebem o MESMO RGB já decodificado;
há cópia IPC para processos separados, não alegação de zero-copy. Ambos permanecem
carregados. Medimos sua comunicação e trabalho, não tempos fictícios para ausentes.

Telemetria/PNGs usam fila assíncrona limitada. Limites de PNG, número de amostras,
telemetria e espaço livre ficam registrados. Falta de espaço encerra como parcial;
não apaga sessões nem troca para o disco cheio. Selagem ocorre fora da thread Tk.

A região mapeada, sua leitura e a performance são observadas na MESMA sessão,
mas não se subtraem tempos de frames diferentes. Deltas contra perfil não são
erros de verdade. Latência de aplicação Tk não é scanout do monitor. Cenários do
motor são outro caminho, explicitamente controlado; LLM/combate completo não estão
conectados. O trabalho não altera ou declara resolvidos os22 apontamentos antigos.

## Verificação

Testes cobrem limites de pixels antes do arredondamento, campos não conectados,
contrato L2/L3, preservação de pixels PNG, chegada tardia dos recortes, filas,
recusa de adulteração e ausência de rótulos neurais. Testes do treinador verificam
oclusão conjunta, separação por vídeo e atualização REAL dos parâmetros.

Workflow dedicado compila E1 e HP1, executa ONNX + OCR + coleta + treinamento e a
UI. Windows empacota e EXECUTA o mesmo EXE nos modos de mapeamento e treinamento.
As imagens/modelos do teste são sintéticos e NÃO são distribuídos como pesos TFT.
Sucesso no CI não significa HUD exata. Conferir estado final do workflow/PR.
