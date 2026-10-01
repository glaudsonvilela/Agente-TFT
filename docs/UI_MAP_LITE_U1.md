# UI-Map Lite U1 — núcleo treinável de localização, separado do leitor

Base de desenvolvimento: `b8d3abb5ed6703857577fa666a4351a3bdc7e438`.

## Escopo entregue

Uma CNN pequena aprende a propor dois cantos e um escore de visibilidade para
**a faixa do banco** e **o conjunto das cinco cartas da loja**. Não identifica
campeões, itens, estrelas, vida ou regras. Não reexecuta B1, S4, Tesseract ou
Grounding DINO. Não altera perfis existentes, catálogo, topologia ou GameState.
O modelo é complementar e experimental, não um substituto do leitor ativo.

A rede tem nove convoluções pequenas, algumas depthwise, normalização durante
treino, pooling e duas camadas lineares. Usa 320x192 RGB. Treino: 131.866
parâmetros; grafo de inferência: 131.274, após incorporar a normalização nas
convoluções. O tamanho e os tempos efetivos são medidos em cada execução.
Não baixa pesos pré-treinados. O prompt/codificador textual do DINO não existe.

## O que é realmente aprendido e medido

Seis fontes da gravação têm hashes fixados. Três fornecem recortes para treino,
uma para validação e duas para teste; a divisão ocorre ANTES das transformações.
O programa deriva as caixas dos perfis B1/loja existentes, sem copiar listas
sazonais e sem usar os números/nome de campeões dos prelabels.

Cada amostra é uma **colagem sintética de recortes reais** em fundo procedural:
banco e loja variam independentemente de posição/tamanho, brilho e contraste.
Algumas regiões são omitidas ou totalmente cobertas. A posição de colagem é
conhecida; isso NÃO prova que a semente original delimitava perfeitamente o
painel nem representa todas as aparências/oclusões possíveis no TFT.

512 exemplos de treino, 96 de validação e 128 de teste; 600 passos fixos, lote
16, CPU duas threads. Otimizador altera pesos reais e o resultado é salvo em
`model.npz`, somente arrays numéricos, sem pickle. Nenhum checkpoint é escolhido
pelo melhor resultado no teste. O relatório inclui todos os positivos/negativos,
abstenções, caixas inválidas e erros nos cantos em pixels da imagem original.

A referência comparada nesse teste é **a geometria fixa sem ajuste**, NÃO as
leituras ou decisões completas do B1/S4. Aumentar a pontuação nesse teste gerado
não significa recuperar ocupação ou melhorar OCR. A fonte real é a mesma
partida: não existe validação independente de partida, patch ou cenário novo.

Os 40 JPEGs originais também recebem inferência, mas **sem rótulos semânticos**.
O visor mostra propostas e referências fixas; nenhuma resposta vira verdade de
treinamento. Não existe ground truth real por frame nesta entrega.

## Treino separado da inferência

O comando reutiliza SOMENTE o Python/PyTorch já instalado pelo B3, sem executar
seu detector e sem instalar/modificar pacotes nesse ambiente. Outra venv,
sem PyTorch/Transformers, contém ONNX/ONNX Runtime, NumPy e Pillow.

O exportador constrói grafo allowlisted (Conv, Relu, AveragePool, Flatten, Gemm,
Sigmoid), incorporando os pesos treinados. Um processo novo confere equivalência
numérica com oito saídas PyTorch, tolerância absoluta 2e-5; falha se divergir.
Usa ONNX CPU, uma thread, sem espera ativa e modelo residente.

O benchmark usa 200 inferências aquecidas, lote um e tensor em memória. Registra
p50/p95 e separa decodificação/redimensionamento do replay. Meta de engenharia:
p95 <=10 ms para esse bloco, não para a captura ou para o agente inteiro. Não
existe garantia de alcançar essa meta no computador do usuário. Consumo do
executor é separado do tamanho dos pesos e do consumo do treinamento.

O binário ONNX Runtime aqui ainda é o pacote padrão, não um build mínimo custom.
A integração direta em Rust, compartilhamento de frames ao vivo, quantização e
refinamento de recortes estreitos na resolução original ficam para a etapa
seguinte. O U1 não pode fornecer recortes de OCR precisos por si só.

## Armazenamento, repetição e segurança operacional

Todo material novo usa a pasta UI-Map no SSD confirmado por montagem + UUID.
O helper existente B3 faz a checagem, incluindo caches/temporários, sem fallback
para `/`. Os JPEGs e o projeto permanecem nos caminhos históricos. Sem sudo,
limpeza, migração, links permanentes ou alterações de banco de adaptação.

Uma chamada é finita; lock impede duas chamadas no mesmo destino. Faltando
ambiente B3 ou fontes, o programa para. Modelos/dados/fontes têm hashes; cada
resultado fica em pasta exclusiva. Relatório só recebe COMPLETE após conclusão.
Interrupção não cria resultado completo nem causa reinício automático.

Opcionalmente um `model.npz` anterior pode ser fornecido ao script para warm
start explícito. Isso inicia um otimizador novo, não retoma exatamente seu estado.
Repetir os mesmos dados NÃO vira nova evidência independente. Não existe ainda
serviço de coleta/treino contínuo, produtor de novas sementes, promoção, limpeza
de quarentena ou ligação do U1 ao executor A16. Esse executor continua especializado
no par HP e não é contornado por um script arbitrário.

## Ubuntu — primeiro ciclo

```bash
cd "$HOME/Agente-TFT" && git switch main && git pull --ff-only &&
TFT_BOARD3_STORAGE_ROOT="/mnt/sherlock-ssd/Agente-TFT/uimap-lite" \
TFT_BOARD3_STORAGE_MOUNT="/mnt/sherlock-ssd" \
TFT_BOARD3_STORAGE_UUID="497aeb76-c1f7-4991-a6c6-5446694f5b18" \
TFT_UI_MAP_TRAIN_PYTHON="/mnt/sherlock-ssd/Agente-TFT/board3/board3-runtime/venv/bin/python" \
bash scripts/train_match001_ui_map_lite.sh
```

Não repetir o experimento pesado B3. O setup novo instala apenas o ambiente de
exportação/inferência no SSD. O limite conservador de 4 GiB do helper de
armazenamento é preservado; treinamento exige 3 GiB de RAM disponível.

Saída: `UIMAP1_EVIDENCE`, `UIMAP1_TRAIN`, `UIMAP1_TRAINED`, `UIMAP1_SUMMARY`,
`UIMAP1_REPORT`, `UIMAP1_COMPARISON`, `UIMAP1_VIEWER`, `UIMAP1_EXIT`.
`evaluation/comparison.txt` é o resumo para envio. `training/` guarda pesos,
plano, curva e resultados; `evaluation/` guarda o ONNX e o visor local.

## Verificação e limites

Há testes de contrato, geração determinística, negativos/abstenção, exportação,
roundtrip de pesos, atualização real de parâmetros e um teste nativo obrigatório
com ONNX em processo novo sem importar torch. Não há teste que declare TFT
resolvido por obter pouca perda em imagens sintéticas. Os resultados reais de
CI e do laboratório ficam no PR, distinguindo ensaio local e medição no PC.

A revisão de código detalhada cobre este módulo e integrações. A varredura
estrutural usa o auditor existente; os apontamentos históricos não são apagados
ou declarados resolvidos. Servidor e vídeos externos continuam adiados.

Fontes técnicas: documentação oficial PyTorch 2.10 Conv2d/BatchNorm2d;
https://onnx.ai/onnx/operators/ ;
https://onnxruntime.ai/docs/api/python/api_summary.html ;
https://onnxruntime.ai/docs/performance/tune-performance/threading.html .
