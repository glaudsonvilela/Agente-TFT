# Continuidade L2

Pedido: núcleo neural extremamente pequeno para localização da interface, complementar
aos leitores existentes, com manutenção por temporada separada e armazenamento no SSD.

Referência local do usuário: L1 192.778 parâmetros, ONNX p95 1,068 ms sobre repetição
de uma imagem preparada; erro elevado e aprovação geométrica falsa. Nenhum mapa ativo.
A comparação L2 usa pesos L1 imutáveis do último experimento completo do usuário.

L2 implementa mapas espaciais TL/BR, contrato comum de aceitação, transformações de
cena inteira em parte dos dados e refinamento local conservador. Não contém detector
de unidades nem reconstrutor 3D; regiões são envelopes iniciais, não rótulos universais.

Não utilizar valores esperados de HP, preço de XP, campeões ou timestamps para escolher
predições. Não treinar L2 com saídas L1 ou B3 como verdade. Não eliminar exemplos ruins
para forçar ganho. Não comparar diretamente métricas históricas com nova distribuição.

Sem alteração de GitHub nesta entrega. Pacote autocontido e patch somente aditivo.
A integração online e Rust, treinamento contínuo, autorização/rollback no runtime e
validação em partidas distintas seguem pendentes.

Antes de continuar: ler report.json/holdout.json/comparison.txt da nova execução e
verificar o selo. Se a localização permanecer grosseira, não autorizar OCR estreito;
melhorar marcos e conjunto de dados preservando o orçamento e a origem das referências.
