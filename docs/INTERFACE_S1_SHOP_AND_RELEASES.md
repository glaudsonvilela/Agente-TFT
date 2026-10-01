# S1 — loja observável e manutenção por camadas

Base: `bd208896f9dfca79b9586f0d3acf9388f82bde0a`. Prioridade do usuário:
HUD local completo antes de servidor/vídeos externos. Nenhum serviço remoto ou
modelo novo é iniciado. A candidata HP3 permanece em quarentena.

## Árvores e responsabilidades

```
configs/topology/       # cardinalidade/ordem lógica, sem campeão ou patch
configs/ui/             # projeção em pixels, idioma, âncoras e aparência
configs/contexts/       # vínculo explícito gravação -> UI + set/patch, ou desconhecido
knowledge/releases/    # set / patch / hash / catálogos e manifesto gerados
rust/...                # algoritmos e contratos genéricos, não lista de campeões
telemetry/data/          # evidências locais e registry; não conteúdo de temporada
```

Tabuleiro padrão: a topologia lógica é reaproveitável (referência 4x7 por lado),
mas coordenadas dependem de projeção, resolução e interface. O arquivo lógico não
é um detector nem centros de células medidos no Match001. Não prometer que toda
arena, modo ou alteração de UI conserva os mesmos pixels. A projeção só muda
quando necessário; catálogo novo não a reescreve.

Dados de campeões, itens, traits, custos e aparência mudam em ritmos diferentes.
Mecânica inédita pode exigir adaptador/código; mudança de dados representáveis
não deve obrigar a copiar um leitor inteiro. Não criar árvore de código por patch.

## Release de conhecimento implementada

`ingestion.knowledge_release` reutiliza os três normalizadores existentes.
Recebe snapshot local, seletor de set, patch TFT, build do provedor e locale.
Esses identificadores são SEPARADOS: patch TFT não é deduzido da versão Data
Dragon/CommunityDragon nem da data do vídeo. URLs emitidas pelos normalizadores
legados com `/latest/game/` são fixadas no build declarado antes de persistir a
release nova. `latest`/`pbe` não são aceitos como build reproduzível.

Cada release tem hash dos bytes de origem, dos componentes e do manifesto.
Mesmo patch com conteúdo novo (ex.: correção intermediária) gera outra identidade;
release anterior é mantida. Repetir a mesma entrada é idempotente. Comparação
`--previous` lista adicionados/removidos/alterados por componente, sem alterar UI,
pesos ou perfil ativo. Endereço de asset diferente não prova mudança nos pixels.
Não baixa assets ou agenda sincronização nesta entrega; recebe os snapshots do
pipeline de ingestão existente. Origem declarada não é assinatura dos dados.

```
python3 -m ingestion.knowledge_release CAMINHO_SNAPSHOT.json \
  --set SELETOR_EXATO --tft-patch PATCH_TFT --source-build BUILD_PROVEDOR \
  --locale pt_br --output-root knowledge/releases
```

O filtro de unidades legado ainda limita custos base 1..5. Ofertas especiais ou
custos fora disso não são forçados a um campeão. Itens preservam escopo do snapshot
do provedor: não inventar associação exclusiva ao set. Augments/regras e detecção
visual de mudanças continuam pendentes de adaptadores próprios.

## Loja S1 funcional

O aplicativo Rust `shop-replay-probe` reutiliza FFmpeg do probe de mídia, as rotinas
de grayscale/cubic existentes, o `visual-match` e o MESMO Tesseract. Um adaptador
comum executa o processo OCR; os perfis numéricos preservam whitelist/PSM/parsers.
O caminho novo PSM6 retorna palavras com coordenadas. Não há segundo OCR/modelo.

Os cinco pares nome/preço são empacotados em um atlas por escala: no máximo DUAS
chamadas OCR por frame de loja localizada, não vinte subprocessos. Duas escalas
continuam sendo uma imagem, não duas evidências independentes. Cada nome/preço
exige concordância 3x/4x e confiança mínima 0.70; score de palavra usa o mínimo,
não média que esconda um token fraco. Palavra atravessando campos invalida a
atribuição do atlas. Custos são texto visível, não custo de catálogo inventado.

O perfil real foi semeado dos JPEGs 150000/200000 ms: duas âncoras de painel e um
marcador de espaço vazio. Os dados de geometria/âncoras ficam em JSON separado
sem vocabulário de campeões. Correspondência visual não é probabilidade calibrada.
`empty_observed` exige marcador, não apenas ausência de OCR. Conteúdo desconhecido
não vira espaço comprado, venda ou evento de compra. As âncoras iniciais podem
abster em controles escurecidos/sobreposições; isso permanece limitação mensurável.

Estados: `unavailable`, `empty_observed`, `unknown`, `partially_readable`,
`offer_text_readable`, `read_error`. Ofertas com texto são ofertas, não necessariamente
campeões: a gravação inclui cartas não convencionais. Não há lookup por timestamp.

Sem contexto de set/patch conhecido, nome e preço podem ser observados, mas
`unit_id` fica null e `catalog_status=not_bound`. O contexto Match001 não contém
versões comprovadas: elas não são preenchidas com o patch atual. A opção de
binding exige release verificada e correspondência explícita de set/patch/locale/UI.
Lookup é por nome exato único, sem correção fuzzy, sem desempate pelo preço.
Preço observado e custo base do catálogo permanecem separados.

## Execução

```
bash scripts/probe_match001_shop.sh
```

Compila somente o binário novo (não sobrescreve o HP3 congelado), usa caminhos e
timestamps dos 40 JPEGs, exclui sugestões/prelabels, não extrai MP4 novamente.
Cria `telemetry/data/match-001-shop-s1.XXXXXXXX`, imprime SHOP1_FRAME,
SHOP1_SUMMARY e SHOP1_REPORT. Timeout do processo de diagnóstico: 240s, grupo
POSIX encerrado em timeout/erro do controlador. Não é daemon nem sandbox.

Binding opcional: `TFT_SHOP_RELEASE` + `TFT_SHOP_CONTEXT`, sem autodetecção de versão
por nome de arquivo. Não é necessário para a primeira medição de texto/visibilidade.

Ainda NÃO entrega cadeado, estado dos botões, catálogo específico da gravação,
inferência de compra, consenso temporal de loja integrado, GameState, banco,
tabuleiro ou itens. Essas lacunas são listadas no relatório, não mascaradas como
HUD completo. Próxima etapa: medir S1, ligar identidades/controles e snapshot
completo ao `shop-runtime` existente; depois banco e tabuleiro.

## Revisão do código

Revisão detalhada nesta entrega: processo Tesseract/TSV, perfil/atlas/observações,
normalizadores e fronteira de versões, scripts/validação. Varredura estrutural
reproduzível de TODOS os Python/Rust/TOML rastreados: sintaxe Python/TOML, membros
do workspace, dependências locais/ciclos, módulos grandes e possíveis cópias.
`full_semantic_review=false`: não equivale a auditoria manual linha a linha de
todo o projeto ou garantia de ausência de bugs. Nada é apagado/autocorrigido.

Achados anteriores preservados: URL `/latest/` nos normalizadores legados;
UnitCatalog ignora parte dos metadados de versão e restringe custos 1..5;
ShopPerception legado não representa vazio explicitamente; BoardDetector é
contrato, não detector visual completo. S1 cerca essas lacunas sem reescrever
módulos em uso e sem declarar o HP corrigido.

Custos HP medidos anteriores e falhas 36/56 continuam diagnóstico, não accuracy.
Nenhuma alteração nos bancos A14/A15 ou no estado do worker. Nenhum treino remoto.

Referências verificadas em 2026-10-01:
- https://support.riotgames.com/en-us/tft/events/patch-schedule-teamfight-tactics
- https://developer.riotgames.com/docs/tft
O calendário usual é aproximadamente quinzenal, com exceções e correções extras.
Data Dragon pode atrasar em relação ao patch; a seleção deve usar versão/dados,
não cronômetro fixo de duas execuções mensais.
