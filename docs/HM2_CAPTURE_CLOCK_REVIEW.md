# HM2 — revisão do relógio da integração

O workflow HUD Mapper HM2 #6 (37015974690), Windows job 110867736110,
passou nos testes nativos de captura, no replay neural/OCR/treino e na interface,
mas falhou ao conectar uma captura real de janela ao mapper. O erro foi:
`Frame com horário futuro incompatível com QPC.` Nenhum pacote HM2 foi publicado
por essa execução. Evidência original: artifact 11230143448, SHA256
`c75ff887ac3173703d86717794c384aedd69526f257e0dcd457a34a47c35b3fa`.

A documentação da Microsoft define SystemRelativeTime como o QPC do frame do
compositor: https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframe.systemrelativetime
Não foi demonstrado se o comportamento observado veio do compositor, do driver
ou de outra condição do runner. Não atribuir a falha ao Vanguard ou a um jogo:
o teste usa uma janela sintética própria.

## Correção de contrato

A captura expõe agora o QPC medido por nosso trabalhador antes da cópia GPU/CPU.
O agendamento usa esse relógio de aquisição e os tempos começam nesse ponto.
SystemRelativeTime permanece bruto e separado, inclusive quando está adiantado
ou retrocede. O registro mostra a diferença assinada e invalida a métrica daquele
timestamp; não modifica o horário original nem inventa latência zero.

Não é latência física da tela ou tempo desde a composição. Os tempos anteriores
que começavam em SystemRelativeTime não são diretamente comparáveis. A frequência,
a ordem das marcações nativas e a ponte com o relógio de recepção continuam validadas.
Uma inconsistência no relógio do próprio trabalhador permanece erro fatal.
Os pixels podem ser coletados com metadados temporais do compositor não resolvidos,
sem virarem gabarito por esse motivo. Treino e geometria não são alterados.

Cinco regressões adicionais cobrem hora normal, compositor futuro, compositor que
retrocede, frequência/ordem inválidas e envio nativo posterior à recepção. O CI deve
continuar exigindo captura real, integração neural/leitores e execução do EXE;
não trocar esse teste por frames simulados ou relaxar confiança OCR.
