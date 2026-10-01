# B1 — Banco/tabuleiro: projeção, evidência visual e visor local

## Checkpoint e escopo

Base: S5 `6b9d8859e9745e7e7fb4b8e875c31f89a8eb3001`. A medição Ubuntu do S5 perdeu quatro leituras de XP e ganhou uma de Atualizar, com 150 chamadas de controles contra 68 no S4. S4 continua referência de desenvolvimento; S5 permanece experimental/opt-in. Não mesclar o melhor resultado histórico por timestamp. Nenhuma decisão aqui altera runtime ou registro ativo.

B1 inicia banco/tabuleiro em vez de outra calibração do mesmo preço. É uma implementação funcional de observação espacial, NÃO um detector completo de campeões ou de ocupação. Não há OCR nesta execução.

## Separação de dados

- `configs/topology/board-standard-4x7-v1.json`: referência lógica existente, preservada.
- `configs/topology/bench-nine-v1.json`: nove espaços lógicos, sem campeões, coordenadas ou patch sazonal.
- `configs/ui/match001-board-bench-v1.json`: projeção, recortes, assinaturas e limites de busca da interface gravada.
- Catálogos por set/patch continuam fora da geometria; B1 não presume a temporada nem vincula identidades.
- O aplicativo reutiliza `BoardGeometry` do `perception-board` e o decoder de mídia já utilizado pelos probes. Não altera o algoritmo legado que associa centros de caixas às células: ele NÃO é chamado para estas propostas.

## Referências visuais disponíveis

O arquivo `0027_001300000ms.jpg` mostra a grade durante uma interação. Os centros das quatro linhas inferiores e das nove posições do banco foram estimados visualmente dessa imagem. A interpolação entre extremos de cada linha é uma projeção de desenvolvimento, não uma calibração geométrica certificada.

`0005_000200000ms.jpg` fornece a aparência inicial do banco vazio e duas referências decorativas da arena. Ambos os JPEGs são identificados por SHA-256 e verificados antes/depois da execução. Nenhum nome, item, contagem de campeões ou prelabel alimenta a inferência.

A gravação mostra arenas diferentes. A estrutura lógica não vira outra temporada só porque o piso mudou. Entretanto, uma assinatura do banco em uma arena não pode estabelecer vazio em outra. Por isso duas regiões independentes precisam corresponder à referência antes da comparação dos espaços do banco. A correspondência NÃO determina quem é o dono do tabuleiro e NÃO identifica fase.

Os frames usados como sementes podem estar também no lote de 40 imagens; a avaliação é diagnóstico de desenvolvimento, não teste independente.

## O que é detectado

O Rust busca trechos horizontais verdes/vermelhos com dimensões, preenchimento e bordas escuras compatíveis com barras de unidades. Lacunas pequenas das divisões da barra são toleradas dentro de limites explícitos. A busca tem limite de pixels, segmentos e candidatos. Se exceder um orçamento, falha explicitamente; não devolve sucesso parcial.

Os resultados são `markers`, candidatos de formato de barra. Há falsos positivos e unidades sem barra visível possíveis. Cor não determina aliado/inimigo. Comprimento não é HP. O índice do marcador é local ao frame, não a identidade persistente de uma unidade.

Cada candidato tem `unit_id=null`, `ground_point=null` e `board_cell=null`. O centro da barra ou do corpo animado NÃO vira ponto de contato no chão. Isso evita colocar unidades na célula errada só para preencher o estado.

## Evidência por espaço do banco

- `empty_reference_match`: recorte semelhante à referência de aparência vazia, por erro RGB e fração de pixels alterados.
- `bar_candidate`: existe uma proposta de barra que intersecta o recorte daquele espaço.
- `ambiguous`: múltiplos candidatos ou conflito entre os sinais.
- `unknown`: não há suporte suficiente; diferença de imagem não vira unidade automaticamente.
- `projection_unavailable`: a arena de referência não foi reconhecida; não reutilizar suas assinaturas.

`occupancy` permanece `null`, inclusive quando há semelhança com a referência vazia. Esses sinais ainda precisam ser combinados com detecção de corpo/base, oclusão e contexto temporal antes de estabelecer presença ou vazio semântico. Todos os 28 estados de célula também ficam desconhecidos nesta entrega. Ausência de barra NÃO é ausência de campeão.

Isso é deliberadamente diferente de preencher nove vazios quando o painel não é reconhecido. B1 expõe os pixels e os sinais para construir a próxima camada, sem declarar banco/tabuleiro concluídos.

## Execução e visor

```bash
bash scripts/probe_match001_board_bench.sh
```

A compilação vai para `rust/target/board-b1`, preservando HP3 e todos os executáveis S3/S5. O script reutiliza os 40 JPEGs, só caminhos/timestamps do manifesto, sem reler o MP4, sem API, servidor, cliques ou treinamento.

A saída exclusiva `telemetry/data/match-001-board-b1.XXXXXXXX/run/` inclui relatório, eventos, comando, manifesto sem labels, logs e `COMPLETE.json` com hashes. As fontes são verificadas antes e depois. Não sobrescreve evidências.

`viewer.html` incorpora as imagens, não usa CDN ou servidor, e permite navegar com botões, slider e setas. Mostra os guias das 28 células, os nove espaços e os candidatos de barra. Por padrão não desenha a projeção como validada numa arena sem correspondência; há um controle explícito para inspecionar o guia não validado. O arquivo é diagnóstico, não uma interface de rotulagem obrigatória.

`scan_ms` mede a análise após decodificação; `decode_and_scan_ms` inclui a decodificação daquele JPEG. A preparação da referência é custo inicial separado. Não comparar esses tempos ao OCR S5 como tarefas equivalentes, nem concluir 60fps em captura contínua.

## Testes e revisão

16 testes Rust novos cobrem geometria, formatos/stride, referência plana, limites, barras azuis ignoradas, corpo verde não tratado como barra, bordas, ticks, ambiguidades e ausência de identidades/ocupação inventadas. O aplicativo inclui os seis testes compartilhados do decoder.

15 testes Python locais cobrem integridade do relatório, status derivados dos scores, geometria, ausência de afirmações semânticas, caminhos e visor autocontido. A integração nativa obrigatória no HUD media usa PNGs sintéticos e Rust/FFmpeg, verifica arena desconhecida, candidatos, relatórios, hashes e recusa de sobrescrita. Um executável-sentinela `tesseract` confirma que o fluxo não chama OCR.

Não há Cargo no ambiente de edição e o clone local falhou por DNS. A compilação e o teste nativo devem ser confirmados no CI. A inspeção dos JPEGs e um protótipo Python de barras são desenvolvimento, não execução do novo binário Rust no Match001. Resultados definitivos de CI ficam no PR; a medição Ubuntu vem depois.

A revisão detalhada limita-se aos módulos alterados e às suas integrações. A varredura estrutural completa permanece obrigatória, sem alegar auditoria semântica de toda a árvore nem resolução dos 22 apontamentos anteriores.

## Próximos marcos

Medir os sinais B1 no lote real; em seguida integrar base/corpo, visibilidade e fase para ocupação efetiva, associar identidades de catálogo versionado e estrelas, e acompanhar cópias distintas entre loja/banco/tabuleiro. Depois itens/painel de atributos (dano, vida, defesas, habilidades) e estado integrado. Cadeado fechado, controles incertos e HP 36/56 continuam pendentes. Servidor e vídeos externos permanecem adiados.
