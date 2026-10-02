# Agente TFT — UI-Map Lite L1

Primeiro núcleo treinável de localização **grosseira** de dois painéis: banco e loja.
Complemento experimental; não substitui B1, S4 ou Tesseract. Não determina ocupação,
campeões, itens, sinergias, profundidade, pontos no chão ou células do tabuleiro.

## Entrega concreta

CNN convolucional separável, 192.778 parâmetros treináveis, RGB 320×192.
Duas saídas `[cx,cy,w,h,visibility_logit]`, coordenadas normalizadas. Sem codificador
textual, catálogo de campeões, download de pesos pré-treinados ou Grounding DINO.
Quatro cantos derivados de cada retângulo são **aproximações**, não keypoints de
alta precisão. O cabeçalho de visibilidade é supervisionado por inserção/remoção/
oclusão sintética, não por conhecimento verdadeiro da visibilidade no Match001.

Treinamento real com 600 passos em CPU, validação separada usada para escolher o
checkpoint, teste uma vez depois da escolha, serialização NPZ sem pickle, exportação
ONNX com comparação numérica PyTorch/ONNX Runtime. O leitor de execução `runtime.py`
não importa Torch e deixa o mapa não acionável. A ligação nativa ao Rust NÃO está
implementada. Os testes ONNX são obrigatórios no comando Ubuntu, mas podem estar
explicitamente ausentes em um ambiente de desenvolvimento sem dependências.

## Uma execução

O instalador `.sh` autocontido é a entrada recomendada. Como alternativa, extraia
este pacote no SSD e rode `bash scripts/run_lite.sh "$HOME/Agente-TFT"`.

Requer a base de armazenamento do PR #30 no projeto. Reutiliza, sem modificá-lo,
o Python/Torch do B3 no SSD. Cria um ambiente pequeno separado com ONNX, ONNX Runtime,
NumPy e Pillow. Não instala CUDA, Transformers ou pesos de outra rede. Os pacotes
transitivos são registrados em `export-environment.txt`; não se afirma um lock
completo de todas as dependências. O treinamento usa Torch; a distribuição do
executor e do modelo não precisa do ambiente de treinamento.

Destino padrão: `/mnt/sherlock-ssd/Agente-TFT/ui-map-lite`. O helper já existente
confere UUID, montagem, caminhos e espaço antes das escritas. Temporários/caches/
ambiente/evidências ficam no SSD. Nenhum dado do usuário é movido ou excluído.
Mantenha o SSD conectado. O programa não promete resistir a retirada forçada do disco.

Limites: uma execução por vez; duas threads de treino; uma no benchmark de inferência;
3 GiB de RAM disponíveis; verificação de 4 GiB livres no destino reutilizada do helper;
900 s para preparação de dependências e 900 s para treino/avaliação. Execução finita,
não daemon nem promessa de treinamento em segundo plano após encerrar a sessão.

## Dados e honestidade da avaliação

A origem é o lote real de 40 JPEGs já disponível. O manifesto só fornece nomes de
arquivos e timestamps. Sugestões de scene/HP/gold/champion NÃO são usadas.

- Treino: recortes das imagens de 150.000 e 200.000 ms.
- Validação: recortes de 250.000 ms.
- Teste: recortes de 300.000 ms.

A separação é feita **antes** da geração de variações; hashes impedem a reutilização
do mesmo arquivo como fonte de outro grupo. Ainda é a **mesma gravação**, com UI e
conteúdo correlacionados: não é validação independente por partida/patch.

Os envelopes iniciais estão em `configs/seed_plan.json`. O banco herda o envelope dos
recortes B1, e a loja usa um envelope grosseiro incluindo controles/cartas. Essas
sementes NÃO são ground truth independente. A supervisão conhecida se refere a onde
o gerador colou um recorte, não à prova de que toda semântica do recorte está correta.

O gerador desloca e redimensiona os dois painéis independentemente, aplica variações
visuais, omite painéis e adiciona oclusões. Fundos vêm da região superior da imagem;
os painéis inferiores originais não ficam escondidos em exemplos rotulados ausentes.
As regiões coladas não se sobrepõem entre si. Recortes e costuras artificiais podem
facilitar o problema, portanto NÃO comprovam adaptação a uma UI naturalmente alterada.

O comparador `fixed_coordinates` é o mapa de sementes sem adaptação. Não é uma
reexecução do algoritmo B1 ou S4. O benchmark de 10 ms é do núcleo residente batch 1,
com aquecimento, sem captura/decodificação/resize/treino; não é o tempo total do agente.
Além disso, todos os 40 originais recebem propostas sem rótulos semânticos; nenhum
resultado nessa parte vira uma taxa de acerto. As leituras antigas não são reexecutadas.

## Saídas

`weights.npz`: pesos realmente treinados, sem objetos serializados/pickle.
`candidate-model.onnx`: somente se exportação e equivalência passaram.
`deployment-candidate.json`: contrato e hash; `activation_allowed=false`.
`report.json`, `holdout.json`, `comparison.txt`: métricas e limitações.
`original-frames.jsonl`, `viewer.html`: propostas sobre originais.
`plan.json`, `sources.json`, `training.jsonl`, `COMPLETE.json`: trilha reproduzível.
Uma falha deixa `FAILED.json` e as evidências, sem sobrescrever outro experimento.

O gate geométrico diagnóstico exige MAE <=20 px, p95 <=40 px e nenhum exemplo
sinteticamente oculto aceito. Mesmo que passe, não permite promover o modelo.
Pontuações de visibilidade não são probabilidades calibradas. O próximo trabalho
é refinamento em resolução original, novas fontes independentes e integração
controlada; não aumentar a confiança artificialmente para obter um relatório favorável.

## Aprendizado contínuo ainda não ligado

Este núcleo já pode **treinar**, e não apenas inferir. A rotina de recolher casos
novos, decidir quando retreinar e ativar/reverter versões ainda falta. A14–A16 não
são alterados, nenhum bloqueio antigo é removido e não há aprendizado por frame.
Novas versões devem usar pacotes versionados e avaliação, não aprender da própria
previsão como se ela fosse a resposta correta.

## Estrutura de código

`common`: contratos/IO; `data`: composição; `model`: rede/loss/pesos;
`evaluate`: métricas; `export`: ONNX/equivalência; `runtime`: inferência sem Torch;
`train`: orquestração finita; `viewer`: diagnóstico local.
O módulo novo é isolado e não copia o motor de OCR, B1 ou os bancos A14–A16.

## Testes

`PYTHONPATH=training python -m unittest discover -s tests -v`

O teste opcional ONNX exige os pacotes de `configs/requirements-export.txt`.
O instalador os prepara e executa esse caminho também. Não há compilador Rust
neste pacote nem alegação de teste nativo Rust concluído.

## Fontes técnicas

MobileNetV3: https://arxiv.org/abs/1905.02244 (motivação para blocos compactos;
não usamos seus pesos ou copiamos a arquitetura integral).
PyTorch ONNX: https://docs.pytorch.org/docs/stable/onnx.html
ONNX Runtime threads: https://onnxruntime.ai/docs/performance/tune-performance/threading.html
Exportador fixo opset 17 usa `dynamo=False` explicitamente para evitar carregar
outro compilador no protótipo. Equivalência numérica obrigatória impede exportação
silenciosamente incompatível. Esse caminho de exportação é distinto do exportador
mais novo recomendado pela documentação.

Base consultada: `b8d3abb5ed6703857577fa666a4351a3bdc7e438`.
Conector GitHub nesta sessão: somente operações de leitura. Nenhum PR/merge foi
publicado. O pacote contém o patch de adição para futura integração, sem alterar
o clone do usuário automaticamente.

O comando Ubuntu também abre um processo novo no ambiente ONNX para medir memória
sem carregar Torch (`LITE1_RUNTIME_SUMMARY`, `torch_loaded=false`). O `comparison.txt`
final fica na pasta-mãe da execução, reunindo o resumo de treinamento e esse teste de
isolamento; os resultados selados em `run/` não são modificados. Essa separação é um
executor de referência em Python/ONNX Runtime, não a integração nativa ao aplicativo Rust.
