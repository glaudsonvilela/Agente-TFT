# UI-Map Lite — preservação dos pacotes L1 e L2

## Por que este checkpoint existe

O usuário pediu confirmação de que as entregas continuavam sendo salvas no GitHub.
Os pacotes L1 e L2 tinham sido entregues como ZIPs/instaladores na conversa, sem
publicação dos seus fontes. Este checkpoint fecha essa lacuna com os arquivos
extraídos, navegáveis e preservados byte a byte. Não é instalação, treinamento,
ativação de modelo ou integração funcional ao runtime.

Base consultada: `97225bb5343fcb84096050689e73bf89efbaf9f3`, que já contém
**UI-Map Lite U1**, integrado pelo PR #31. U1 não é o mesmo pacote que L1.
Nenhum arquivo existente dessa base foi alterado.

| Identidade | Local | Estado nesta publicação |
|---|---|---|
| U1 do PR #31 | Caminhos já existentes no projeto | Preservado; 131.866 parâmetros de treino / 131.274 no grafo descrito pelo PR |
| L1 do instalador da conversa | `experiments/ui_map_lite_l1/` | Fonte congelado, 192.778 parâmetros; não promovido |
| L2 do instalador da conversa | `experiments/ui-map-lite-l2/` | Fonte congelado, 27.726 parâmetros; não promovido |

Os nomes dos diretórios são os dos patches originalmente entregues, inclusive a
diferença entre sublinhados e hífens. Não mover arquivos para os caminhos de U1 nem
carregar pesos de U1 em L1/L2 apenas por semelhança de nome. Uma futura integração
precisa comparar os contratos e escolher explicitamente os módulos compartilhados.

## Integridade e conteúdo

Foram preservados os **16 arquivos do diretório de pacote L1 e 22 do L2**, incluindo
código, testes, configuração, scripts, documentação e seus `PACKAGE_MANIFEST.json`.
Os 15 hashes de conteúdo do manifesto L1 e os 21 do L2 foram conferidos antes da
publicação. As árvores Git criadas no servidor correspondem exatamente às árvores
calculadas a partir dos arquivos extraídos dos ZIPs.

Os cinco arquivos `legacy_l1` presentes no L2 continuam sendo a cópia congelada
fornecida pelo pacote original. Não foram substituídos pelo U1. Não foi feita limpeza
semântica que alterasse os experimentos durante esta preservação.

Os README/manifests originais ainda contêm frases como "não publicado" e
`remote_published: false`: elas registram o estado **na entrega original do ZIP**.
Foram mantidas para não invalidar os hashes. O estado desta publicação é documentado
neste arquivo e no PR, e não deve ser inferido daqueles campos históricos.

Não foram enviados vídeos, JPEGs, visores com imagens incorporadas, ambientes Python,
caches ou pesos treinados. Os scripts de execução fazem parte dos fontes; os
instaladores autocontidos e os ZIPs de evidências continuam sendo artefatos separados
da conversa/SSD, identificados por hash em `UI_MAP_LITE_PUBLICATION.json`.

## Verificação realizada nesta publicação

Ambiente local: Python 3.13.5, Torch 2.10.0+cpu, NumPy 2.3.5 e Pillow 12.3.0.

- L1: 34 testes encontrados, **33 passaram e 1 foi ignorado explicitamente**.
- L2: 44 testes encontrados, **43 passaram e 1 foi ignorado explicitamente**.
- Os dois testes ignorados exigem ONNX/ONNX Runtime, ausentes neste ambiente.
- Sintaxe dos 27 arquivos Python e dos dois scripts shell verificada.
- Nenhum novo treinamento completo, benchmark ou execução no SSD do usuário.

Comandos locais de teste, executados dentro de cada diretório de pacote:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=training OMP_NUM_THREADS=1 \
OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python3 -B -m unittest discover -s tests -v
```

Esses resultados não comprovam precisão da interface e não substituem a integração
ONNX. A suíte geral do repositório não deve ser anunciada como execução automática
destas duas suítes isoladas sem verificar os jobs. Nenhum workflow foi alterado neste
checkpoint. Os 22 apontamentos históricos de manutenção não foram declarados resolvidos.

## Estado funcional preservado

L1 tem limitações conhecidas de coordenadas e uma diferença entre aceitação por
visibilidade nas métricas e a decisão geométrica do runtime. L2 conserva o contrato
compartilhado de decisão e o refinamento de bordas descritos no pacote. Nenhum dos
dois está aprovado para recortes estreitos de OCR. Não houve alteração de B1, S4,
Tesseract, catálogos sazonais, GameState, pesos estratégicos ou registros A14–A16.

A medição L1 enviada pelo usuário não deve ser atribuída ao U1 do PR #31. A última
entrega L2 ainda aguardava o comparativo do usuário neste ponto da conversa.
As métricas de composições geradas não são acurácia em partidas independentes.

Próxima integração: reconciliar os caminhos U1/L1/L2, preservar os pesos de referência,
executar as verificações ONNX pertinentes e incorporar apenas após revisão. Publicar
o código para continuidade não remove bloqueios nem autoriza aprendizagem contínua
ou ativação automática. O estado de merge deve ser consultado no PR.
