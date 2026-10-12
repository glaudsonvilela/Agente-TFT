# Aprimoramentos: leitura do Motor 1 no Motor 2

O leitor OCR mantém as três cartas observadas como hipóteses. Para cada uma,
envia texto da imagem, IDs candidatos, descrição de referência, origem dos
IDs e a regra conhecida do patch 18.4B. Cartas temporariamente desativadas
permanecem no catálogo. O resumo enviado ao Rust inclui versão e tamanho do
catálogo, horário da leitura e os indicadores de escolha e verdade de treino.

O Motor 2 guarda esses dados na observação da partida, conserva as hipóteses
durante até 3,5 s no mesmo epoch e as limpa assim que a janela de escolha
fecha. O estado em Rust resume quantas cartas foram ligadas a um ID único,
quantas têm IDs ambíguos e quais entram em conflito com uma regra conhecida da
versão de referência. Conflito não é prova de erro na imagem: o patch do cliente
gravado não foi confirmado. Nenhuma carta é marcada como escolhida pelo OCR.

## Verificação

Na captura de escolha em 2-1 enviada pelo usuário, o OCR levou cerca de 2,0 s.
O pedido real ao processo `agente-tft-e1-worker` retornou:

| Campo do Motor 2 | Resultado |
| --- | ---: |
| ofertas recebidas | 3 |
| ID único | 1 (Acólito da Congregação das Bruxas) |
| IDs ambíguos | 2 (Estudo Paciente, Vigarista) |
| patch do cliente confirmado | não |
| escolha observada / rótulo de treino | não / não |
| erro de memória Rust | nenhum |

O processo Rust não recomendou uma escolha com essa observação isolada. A
ligação de dados está ativa; avaliar qual carta selecionar requer estado da
partida e regras do patch confirmadas, e treinar com resultado requer a escolha
e o desfecho observados.
