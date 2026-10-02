# Checkpoint L1

Pedido: um núcleo neural realmente pequeno para localizar a interface, complementar
B1/S4/Tesseract e reduzir remapeamentos; arquivos pesados no SSD XS1000, não na raiz
quase cheia. Servidor e vídeos externos continuam adiados.

Implementação L1: rede de envelopes de banco/loja, treinamento CPU finito, dados
sintéticos derivados de sementes reais, fontes separadas antes de augmentations,
pesos NPZ sem pickle, exportador ONNX com verificação, executor de referência
ONNX Runtime independente de Torch e relatório/visor automatizados.

Não confundir a prova de treinamento/latência do núcleo com precisão suficiente.
Ainda faltam: refinamento local em pixels originais; keypoints semânticos confiáveis;
fontes de avaliação por partida/patch; adaptação do runtime Rust; supervisor assíncrono;
integração A14–A16 para nova categoria; aprovação/reversão de modelos e ciclo contínuo.
Não alterar OCR/HP/quarentena nem interpretar candidatos como ocupação do tabuleiro.

Comparativos históricos B1×B3 não são semanticamente iguais ao teste de mapa.
L1 mede coordenadas e visibilidade em composições conhecidas. Não usar 148 caixas
ou 232 barras como referência de acerto do localizador.

L1 é limitado: dois exemplos fonte para treinamento, uma fonte para validação e uma
para teste na mesma gravação. Modificações sintéticas não equivalem a um novo patch
real. Cortes/composição podem oferecer pistas artificiais. Métricas na imagem natural
continuam sem ground truth. Não baixar limiares para liberar a candidata.

Arquivos de execução: `/mnt/sherlock-ssd/Agente-TFT/ui-map-lite/`.
Código do projeto/B1 ainda em `/home/hobit/Agente-TFT`.
UUID: `497aeb76-c1f7-4991-a6c6-5446694f5b18`.
O helper de storage do PR #30 é reutilizado por hash, sem cópia/modificação.

Primeira edição não publicada no GitHub: ferramentas disponíveis só de leitura,
sem `create_tree`/commit/merge e sem acesso de rede no Git do container. Foi criado
instalador autocontido e patch. Não afirmar que o código está em `main`.
