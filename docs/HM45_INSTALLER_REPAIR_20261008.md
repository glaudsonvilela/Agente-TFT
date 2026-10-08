# Correção da instalação e da seleção de captura HM4.5

## Evidências do teste anterior

- O `setup.log` do Windows registrou extração, importação da VM e teste de saúde concluídos. A falha relatada ocorreu depois, na interface do aplicativo.
- A interface do designer tinha comandos de demonstração e comandos reais para os mesmos botões de captura. O código de demonstração não deve agir no modo conectado.
- A verificação anterior do pacote confirmava que a página local abria, mas não executava o binário Rust que enumera as fontes de captura.
- A moldura lilás vinha do fundo e das margens da apresentação do designer, que também eram aplicadas ao aplicativo instalado.
- As primeiras páginas brancas eram do extrator Inno mostrado antes do assistente visual.
- O servidor da interface encerrava depois de 30 segundos sem consultas. Navegadores podem suspender consultas quando outra janela está em primeiro plano. O assistente da VM também encerrava depois de 60 segundos de inatividade.
- O início da captura esperava até 30 segundos por um modelo atualizado do servidor. Uma falha de rede impedia o uso do modelo visual já incluído no pacote.

## Mudanças

- O aplicativo conectado ocupa toda a janela escura, sem margem, borda ou sombra da apresentação.
- O seletor mostra carregamento, erro da enumeração e botão de tentar novamente. O código de demonstração ignora seus comandos no aplicativo conectado.
- O pacote Windows só passa na verificação se o capturador Rust estiver presente e responder ao comando `list`.
- Um iniciador Rust abre a arte original do instalador antes da extração. Ele verifica o SHA-256 do pacote anexado, executa o Inno em modo silencioso e passa a mesma janela ao assistente real da VM.
- Uma captura ativa não é encerrada pela pausa das consultas da interface. Sem captura, o fechamento por inatividade ocorre após dez minutos; no assistente, após trinta minutos.
- A sessão usa imediatamente o modelo local disponível. A consulta de atualizações continua em segundo plano para futuras sessões.

## Verificação realizada no Ubuntu

- Teste com navegador Chromium: escolher a janela, iniciar sessão local simulada, apresentar falha da enumeração e recuperar com nova consulta.
- Teste visual em Chromium a 1120 × 800: primeira tela do instalador com o fundo escuro e a arte do designer, sem borda externa.
- Testes Python de ponte local e assistente da VM: 10 aprovados, incluindo o início de captura sem esperar o servidor.
- Testes Rust do iniciador: página servida em IP local, integridade do pacote e rejeição de pacote alterado: 4 aprovados.

## Verificação pendente no pacote Windows

O pipeline de Windows deve compilar o iniciador, testar a integridade do `.exe` final, executar a enumeração real de monitores e janelas pelo binário Rust empacotado, testar a ponte do assistente e validar uma decisão por replay gravado. O comportamento na sessão gráfica do computador do usuário só pode ser confirmado no Windows dele.
