# Correção da instalação e da seleção de captura HM4.5

## Evidências do teste anterior

- O `setup.log` do Windows registrou extração, importação da VM e teste de saúde concluídos. A falha relatada ocorreu depois, na interface do aplicativo.
- A interface do designer tinha comandos de demonstração e comandos reais para os mesmos botões de captura. O código de demonstração não deve agir no modo conectado.
- A verificação anterior do pacote confirmava que a página local abria, mas não executava o binário Rust que enumera as fontes de captura.
- A moldura lilás vinha do fundo e das margens da apresentação do designer, que também eram aplicadas ao aplicativo instalado.
- As primeiras páginas brancas eram do extrator Inno mostrado antes do assistente visual.
- O primeiro ensaio do iniciador Rust empacotado no Windows terminou com `0xC00000FD` (estouro da pilha): o buffer de extração de 1 MiB cabia nos testes Rust, mas não na pilha da thread principal do `.exe` GUI. O buffer foi movido para a memória dinâmica e o executável completo deve passar novamente pelo ensaio de integridade.
- O servidor da interface encerrava depois de 30 segundos sem consultas. Navegadores podem suspender consultas quando outra janela está em primeiro plano. O assistente da VM também encerrava depois de 60 segundos de inatividade.
- O início da captura esperava até 30 segundos por um modelo atualizado do servidor. Uma falha de rede impedia o uso do modelo visual já incluído no pacote.

## Mudanças

- O aplicativo conectado ocupa toda a janela escura, sem margem, borda ou sombra da apresentação.
- O seletor mostra carregamento, erro da enumeração e botão de tentar novamente. O código de demonstração ignora seus comandos no aplicativo conectado.
- O pacote Windows só passa na verificação se o capturador Rust estiver presente e responder ao comando `list`.
- Um iniciador Rust abre a arte original do instalador antes da extração. Ele verifica o SHA-256 do pacote anexado, executa o Inno em modo silencioso e passa a mesma janela ao assistente real da VM.
- Uma captura ativa não é encerrada pela pausa das consultas da interface. Sem captura, o fechamento por inatividade ocorre após dez minutos; no assistente, após trinta minutos.
- A sessão usa imediatamente o modelo local disponível. A consulta de atualizações continua em segundo plano para futuras sessões.
- Quando a prévia já cabe em 720p, o capturador Rust copia linhas inteiras sem iterar sobre cada pixel. A codificação JPEG passou a esperar até o próximo quadro, sem a pausa fixa de 10 ms que podia perder o prazo de 30 FPS; as métricas de FPS são zeradas ao trocar de sessão.
- Ao clicar em “Abrir Agente TFT”, o assistente espera a nova interface local responder e navega para ela na mesma janela. Se o processo encerrar ou não abrir no prazo, o erro permanece visível no assistente.
- A conexão MJPEG deixa de reenviar uma imagem antiga quando não chega quadro novo; o ensaio de regressão cobre uma pausa superior a dois segundos.
- A leitura de FPS e a troca de sessão agora usam a mesma sincronização da prévia. Um quadro da sessão anterior não pode substituir a imagem da sessão nova. A cada cinco segundos, o log registra FPS codificado, tempo de codificação, quadros nativos recebidos e substituições na fila para análise posterior.
- A prévia conectada agora pede somente o próximo JPEG ao servidor local, desenha no canvas e libera a imagem decodificada após cada quadro. O aplicativo mostra o FPS efetivamente desenhado. A requisição pendente é cancelada ao trocar de tela ou fechar a janela.
- O capturador Rust seleciona a prévia por intervalos fixos de tempo. Isso evita reiniciar o prazo quando os eventos WGC chegam com pequenas variações. A cadência de análise permanece separada.

## Verificação realizada no Ubuntu

- Teste com navegador Chromium: escolher a janela, iniciar sessão local simulada, apresentar falha da enumeração e recuperar com nova consulta.
- Teste visual em Chromium a 1120 × 800: primeira tela do instalador com o fundo escuro e a arte do designer, sem borda externa.
- Testes Python de ponte local e assistente da VM: 15 aprovados, incluindo o início de captura sem esperar o servidor e a entrega de um quadro novo sem repetir a imagem antiga.
- Testes Rust do iniciador: página servida em IP local, integridade do pacote e rejeição de pacote alterado: 4 aprovados.
- Ensaio isolado do fluxo MJPEG por IP local: 297 quadros de aproximadamente 515 KiB em 9,83 segundos (30,1 FPS entregues; intervalo p95 de 33,8 ms). Isso testa o transporte local, não a captura Windows nem a decodificação visual no computador do usuário.
- Ensaio local do codificador da interface com 120 quadros sintéticos em 4 segundos: 120 JPEGs produzidos (30 FPS), 7,75 ms no percentil 95 e nenhum quadro substituído. Isso não mede a aquisição WGC nem o navegador.
- Ensaio local de 45 segundos do fluxo MJPEG com decodificação no Chromium: 1.349 mudanças de imagem observadas (29,98/s), intervalo p95 de 33,4 ms e nenhum intervalo acima de 100 ms. Isso mede o servidor e o navegador locais sem captura WGC.
- Ensaio de resistência do mesmo caminho por 330 segundos, com JPEGs sintéticos de cerca de 512 KiB: 9.866 mudanças observadas (29,9/s), intervalo p95 de 33,4 ms e duas pausas acima de 100 ms. Não houve degradação progressiva visível nesse recorte; captura WGC e analisador não participaram.
- Dez quadros de uma sessão TFT anterior, reduzidos para no máximo 720p com qualidade JPEG 72, produziram arquivos com mediana de 115 KiB (máximo 143 KiB) e mediana de codificação de 3,61 ms no Ubuntu. É uma amostra pequena, mas o ensaio sintético acima transferiu quadros aproximadamente quatro vezes maiores.
- Navegação real no Chromium entre o assistente visual simulado e o estúdio conectado: botão de abertura, resposta da ponte local e página final carregada na mesma janela.
- O elemento MJPEG antigo manteve os quadros, mas o total de memória residente dos processos Chromium foi de cerca de 1.375 MiB no início para 1.535 MiB após 330 segundos, mesmo sem o resto da interface. Uma página Chromium parada ficou próxima de 900 MiB nas duas medições.
- Com pedidos individuais e liberação explícita das imagens decodificadas, foram desenhados 9.908 quadros em 330 segundos (30,02 FPS), sem erro nem intervalo acima de 100 ms. O processo Python que serviu os quadros permaneceu perto de 53 MiB. O total dos processos Chromium foi de 956 para 1.136 MiB; parte desse salto veio da abertura de um processo auxiliar de aproximadamente 160 MiB do próprio Chromium durante o teste. Esses totais não isolam com precisão a memória do decodificador, mas a nova rota manteve cerca de 400 MiB a menos que a rota MJPEG nas duas janelas de medição.
- A interface conectada completa desenhou uma imagem TFT em mudança, indicou 30 FPS exibidos e não registrou erro JavaScript em um ensaio curto. Fechar a janela durante um quadro pendente não deixa mais exceção no servidor.

## Fluidez: evidência e limite atual

Na sessão Windows antiga de outubro, a captura Rust tinha recebido 21.061 eventos em 394 s e processado 11.481 quadros (cerca de 29/s), enquanto a janela registrou 23,6 FPS perto do fim. Em um ensaio posterior de 330 s com janela sintética, o capturador recebeu 10.812 eventos WGC e entregou 7.901 prévias: 23,96 FPS no começo e 23,86 no fim. O desenho teve p95 de 0,44 ms, o trajeto da aquisição à recepção em Python teve p95 de 6,37 ms e a memória privada cresceu 4,0 MiB. Assim, a lentidão nesse teste não veio de desenho caro nem de crescimento progressivo da memória Python.

Depois do ajuste da cadência, o mesmo ensaio recebeu 10.897 eventos WGC e entregou 8.151 prévias em 330 s: 24,52 FPS no começo e 24,77 no fim. A melhora foi pequena. O intervalo p95 entre quadros desenhados continuou perto de 63 ms, com 174 intervalos acima de 66 ms; o desenho custou 0,45 ms no p95, o trajeto da aquisição à recepção em Python levou 5,23 ms no p95 e a memória privada cresceu 3,9 MiB. Isso indica que a cadência dos eventos da janela sintética ou outra etapa anterior ao desenho ainda limita este ensaio. É uma inferência a partir dos totais; os horários individuais dos eventos WGC não foram registrados. O teste não mede o replay no computador do usuário nem a janela nova do navegador junto com a captura Rust.

Separadamente, o caminho local de JPEG para o navegador exibiu 30 FPS por 330 s com imagens TFT e 30 FPS por 90 s com imagens de cerca de 524 KiB. A ausência de travamento progressivo nesses testes e no ensaio nativo é evidência útil, mas a fluidez completa só pode ser confirmada com WGC, análise e navegador simultâneos no Windows do jogador.

## Verificação do pacote Windows

O pipeline Windows do commit `a7b3f0e1` terminou com sucesso. O `.exe` empacotado passou na verificação SHA-256 do iniciador e na leitura dos recursos do designer. O aplicativo empacotado enumerou quatro fontes reais do executor, abriu a ponte local, confirmou o modelo visual incluído e produziu uma dica de subir de nível a partir de um replay gravado, com transporte de voz simulado. O áudio ElevenLabs real e a instalação WSL2 na sessão gráfica do computador do usuário ainda precisam da prova de campo.
