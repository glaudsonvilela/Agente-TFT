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

## Verificação realizada no Ubuntu

- Teste com navegador Chromium: escolher a janela, iniciar sessão local simulada, apresentar falha da enumeração e recuperar com nova consulta.
- Teste visual em Chromium a 1120 × 800: primeira tela do instalador com o fundo escuro e a arte do designer, sem borda externa.
- Testes Python de ponte local e assistente da VM: 10 aprovados, incluindo o início de captura sem esperar o servidor.
- Testes Rust do iniciador: página servida em IP local, integridade do pacote e rejeição de pacote alterado: 4 aprovados.
- Ensaio isolado do fluxo MJPEG por IP local: 297 quadros de aproximadamente 515 KiB em 9,83 segundos (30,1 FPS entregues; intervalo p95 de 33,8 ms). Isso testa o transporte local, não a captura Windows nem a decodificação visual no computador do usuário.
- Ensaio local do codificador da interface com 120 quadros sintéticos em 4 segundos: 120 JPEGs produzidos (30 FPS), 7,75 ms no percentil 95 e nenhum quadro substituído. Isso não mede a aquisição WGC nem o navegador.
- Ensaio local de 45 segundos do fluxo MJPEG com decodificação no Chromium: 1.349 mudanças de imagem observadas (29,98/s), intervalo p95 de 33,4 ms e nenhum intervalo acima de 100 ms. Isso mede o servidor e o navegador locais sem captura WGC.
- Ensaio de resistência do mesmo caminho por 330 segundos, com JPEGs sintéticos de cerca de 512 KiB: 9.866 mudanças observadas (29,9/s), intervalo p95 de 33,4 ms e duas pausas acima de 100 ms. Não houve degradação progressiva visível nesse recorte; captura WGC e analisador não participaram.
- Dez quadros de uma sessão TFT anterior, reduzidos para no máximo 720p com qualidade JPEG 72, produziram arquivos com mediana de 115 KiB (máximo 143 KiB) e mediana de codificação de 3,61 ms no Ubuntu. É uma amostra pequena, mas o ensaio sintético acima transferiu quadros aproximadamente quatro vezes maiores.
- Navegação real no Chromium entre o assistente visual simulado e o estúdio conectado: botão de abertura, resposta da ponte local e página final carregada na mesma janela.

## Fluidez: evidência e limite atual

O último ensaio nativo de 330 segundos disponível no SSD mediu 23,58 FPS nos primeiros 30 segundos e 22,80 FPS nos últimos 30 segundos, com aumento de memória privada de 4,2 MiB. Ele usou uma janela animada sintética em um executor Windows de CI. A queda sustentada por acúmulo de memória não apareceu nesse ensaio, mas a meta de 30 FPS também não foi atingida. O ensaio por IP local acima entregou 30 FPS, de modo que o transporte isolado não explica sozinho a taxa nativa menor. Ainda é necessário medir aquisição Rust, codificação JPEG e exibição juntos na sessão gráfica real para localizar o componente que limita o FPS.

O próximo relatório de resistência Windows separa os tempos de cópia GPU, conversão, envio por IPC e entrega Python; inclui a taxa recebida, os quadros substituídos e intervalos acima de 66 ms. Isso permite localizar a perda sem inferi-la apenas pelo FPS desenhado.

Na sessão Windows antiga de outubro, a captura Rust tinha recebido 21.061 eventos em 394 s e processado 11.481 quadros (cerca de 29/s), enquanto a janela registrou 23,6 FPS perto do fim. O novo ensaio nativo de CI, com uma janela sintética, entregou 7.832 prévias em 330 s (23,7/s), quase sem descarte na fila (um quadro). Naquele ensaio, os percentis 95 foram 1,77 ms para a cópia GPU, 2,03 ms para a conversão, 2,27 ms para escrita IPC, 6,56 ms até a entrega Python e 0,43 ms para o desenho; a memória privada subiu 3,8 MiB. A janela sintética gerou 10.838 eventos WGC, mas o ensaio ainda não mede a cadência real de atualização da origem. Portanto, seus 23,7 FPS não provam que uma fonte de replay a 30 FPS será limitada da mesma forma. O teste com navegador acima confirma a capacidade do trecho posterior à captura no computador Ubuntu.

## Verificação pendente no pacote Windows

O pipeline de Windows deve compilar o iniciador, testar a integridade do `.exe` final, executar a enumeração real de monitores e janelas pelo binário Rust empacotado, testar a ponte do assistente e validar uma decisão por replay gravado. O comportamento na sessão gráfica do computador do usuário só pode ser confirmado no Windows dele.
