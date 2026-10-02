# L3 — resultado recebido e auditoria da composição

Fonte: `comparison.txt`, 24.682 bytes, SHA-256
`c433d76602fc7f6f87b8d2d348a648151a0e17bd86aee9f3d3bf4b1ed7385392`.
Foram recebidos os agregados `LITE3_SUMMARY` e `LITE3_RUNTIME_SUMMARY`, não
os pesos desta execução, `holdout.json`, registros por frame ou selo completo.
Código revisado: `4e1537375fd3b5e806ae53eca282d0a2c0d29668`, PR #33.
Esta atualização preserva os resultados; não altera o renderer/modelo ativo.

## Conclusão de desenvolvimento

Manter L2 como referência comparativa, sem aprová-lo para produção, e L3 como
candidata diagnóstica. O custo foi reduzido; precisão, visibilidade e tabuleiro
continuam não resolvidos. Nenhum perfil, GameState, OCR ou peso é modificado.

## Tempo e memória informados pelo usuário

- ONNX residente: p50 **1,460939 ms**, p95 **1,5685713 ms**, 40 tensores distintos,
  120 repetições após 30 aquecimentos; não inclui preparação/refinamento.
- Preparação: p50 **22,1808755 ms**, p95 **29,8137223 ms**.
- Total por arquivo SEM refinamento: **24,5434895 / 31,5033667 ms** (p50/p95).
- Diagnóstico de bordas separado: **1,226329 / 2,23381495 ms**.
- RSS máximo: 167.968 KiB, aproximadamente **164,03 MiB**, não apenas pesos.
- Na comparação pareada do refinador L2 nesta mesma execução: p50
  **12,21686 -> 1,618178 ms**, com propostas idênticas. Razão das medianas 7,55.
- O total histórico L2 de 48,03 ms incluía refinamento. Não declarar que o L3
  ficou 49% mais rápido em trabalho equivalente, nem somar percentis.

## Geometria no MESMO ensaio gerado

| Região | MAE L2 -> L3 (px) | P95 do maior desvio por retângulo L2 -> L3 (px) |
|---|---|---|
| Banco, agregado | 6,5075 -> 6,3336 | 31,0645 -> 31,9210 |
| Loja, agregado | 5,3729 -> 4,7352 | 29,6363 -> 32,8134 |
| Banco, context_paste | 12,1502 -> 13,4888 | 60,1007 -> 101,0574 |
| Loja, context_paste | 8,5475 -> 8,4734 | 44,1069 -> 69,0786 |
| Banco, whole_scene | 4,1991 -> 3,4064 | 17,8645 -> 13,5695 |
| Loja, whole_scene | 3,7856 -> 2,8661 | 11,3941 -> 8,5502 |

A média melhora no agregado, mas o contexto colado continua com caudas piores.
Mesmo entre propostas aceitas, o banco context_paste tem P95 de **80,5900 px**;
logo os extremos não são apenas caixas rejeitadas pelo validador.

Aceites ocultos: L2 banco/loja **0/1**; L3 **1/2**. Os sete bloqueios diagnósticos
repetem agregados e subgrupos: NÃO são sete imagens diferentes. São três aceites
indevidos de painel no agregado, sem demonstrar que ocorreram em três imagens.
No grupo negative_scene ambos recusam todos os 37 exemplos; são variações da fonte
negativa de teste, não 37 partidas independentes.

Todos os quatro limites a até 4 px: L3 banco **24/124**, loja **34/120**. A até
1 px: zero em ambos. Isso não é mapa exato nem autorização para OCR estreito.
Geometry-invalid não equivale a out-of-frame: inclui ordem/tamanho e painéis ausentes.
Os agregados não revelam o canto ou frame de cada falha.

## Novo achado reproduzido: um painel pode cobrir o outro sem atualizar o rótulo

`training/uimap_path_l3/data.py`, blob Git
`02f90741849edee3998d214f39a8fd980f833af1`, cola banco e depois loja.
Cada caixa é marcada visível ao verificar seus próprios limites; não há uma etapa
posterior que atualize a visibilidade do banco pela loja ou por um retângulo de
oclusão destinado à outra região. As faixas de posição permitem a interseção.

A reprodução do corpo original de `Renderer.sample`, sem modificar sua sequência
aleatória, encontrou:

| Conjunto | Amostragens | Envelopes sobrepostos | Ambos com visible=1 |
|---|---:|---:|---:|
| Treinamento | 768 | 8 | 6 |
| Validação | 96 | 0 | 0 |
| Teste | 192 | 2 | 2 |

Nas oito interseções do treino, o banco permanece visible=1. Duas também têm um
retângulo de oclusão da loja atravessando o banco sem atualizar seu rótulo.
Na seed **80300396**, a loja é colada por cima de aproximadamente **41,41%** do
envelope do banco e ambos ficam visible=1. Uma renderização real com pixels
sintéticos distintos confirmou que o pixel (1000,825), dentro das duas caixas,
pertence à loja colada depois, enquanto o banco continua rotulado visível.

As duas seeds de teste com interseção são **80330012** e **80330053**. As contagens
por modo (106 whole_scene, 49 context_paste e 37 negative_scene) e visibilidade
(124 banco e 120 loja) da reprodução coincidem com o resumo recebido.

Isto comprova uma dependência de oclusão não representada no gerador. NÃO comprova
que essas seeds causaram os maiores erros ou os três aceites ocultos da rede:
os registros individuais e os pesos do usuário não foram recebidos. Rótulos de
painel parcialmente coberto precisam de semântica explícita e, para precisão dos
cantos, disponibilidade por ponto; não é correto exigir coordenada observável e
ignorar a camada que a encobre. Não descartar retroativamente os casos difíceis.

## Reprodução e alcance da revisão

`experiments/audits/l3_renderer_geometry.py` executa o método do fonte congelado
com operações de imagem substituídas por objetos de teste para o levantamento
geométrico; depois renderiza UM exemplo com Pillow e pixels sintéticos.
Não usa imagens privadas, não inicializa o modelo, não treina e não executa OCR.
A criação normal do Renderer é substituída pela fixture; não valida manifestos do
usuário ou o SSD. O hash do código é obrigatório, inclusive com Python -O.

Localmente: consistência de contagens e médias ponderadas de seis pares
método/painel verificada; bloqueios reconstruídos conforme evaluate.py; 1.056
amostragens geométricas e uma renderização sintética confirmadas. Também foram
verificadas recusa de fonte alterada, recusa de sobrescrita e sintaxe do auditor.
Não foi reexecutada a suíte completa, ONNX ou treinamento nesta revisão.
Nenhum resultado novo de CI é presumido para este commit de auditoria.

## Próxima correção conjunta, ainda não implementada nesta atualização

1. Separar posições propostas, máscaras efetivamente renderizadas e rótulos
   finais; computar oclusão após todas as colagens e coberturas.
2. Definir visibilidade por painel E pelos pontos necessários ao mapa; não
   aceitar cantos extrapolados como pixels observados. Preservar abstenção.
3. Manter antigos gerador, datasets e métricas congelados. Corrigir em versão
   explícita; comparar os dois painéis sem escolher o melhor modelo por campo.
4. Correlacionar falhas com os registros já salvos antes de novo treino; não
   repetir 1.400 passos apenas para variar a sorte. Não baixar limiares.
5. Continuar com preparação compartilhada e bordas limitadas. Uma caixa válida
   de banco/loja não estabelece landmarks de chão ou células do tabuleiro.

O próximo treino só poderá demonstrar ganho após essa correção de supervisão e
nova avaliação declarada. O achado não resolve, sozinho, precisão, generalização
ou autoaprendizado contínuo. Os 22 apontamentos históricos permanecem abertos.
