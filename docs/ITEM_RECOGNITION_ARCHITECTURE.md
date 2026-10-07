# Reconhecimento de itens: inventário e campeões

## Diagnóstico em 7 de outubro de 2026

O banco atual usa ícones versionados da Riot e compara recortes por RMS de pixels
(`training/board_hub_item_candidates.py`). Há também uma CNN de 193 classes
(`apps/hud_mapper/hm/item_neural.py`). Ela foi treinada com variações sintéticas
dos ícones oficiais: a avaliação em replay contém cinco recortes, de quatro
itens, todos da mesma sessão. Isso não mede precisão em partidas independentes.
O leitor ao vivo ainda devolve candidatos sem confirmar item, portador ou
movimento entre inventário e tabuleiro.

## Caminho escolhido

1. **Recortar antes de reduzir a prévia.** A captura Rust mantém o quadro na
   resolução nativa apenas tempo suficiente para localizar e recortar os ícones
   pequenos. A prévia continua independente a 720p. Âncoras da interface e
   escala detectada definem os espaços de inventário e os ícones sob as barras
   de vida; coordenadas de uma única gravação não servem para todas as telas.
2. **Separar ocupação, identidade e portador.** Primeiro decidir se o espaço
   contém ícone, pilha/contador, efeito temporário ou nada. Depois identificar
   o item. Por último associar o ícone equipado à unidade rastreada. Cada
   resultado tem evidência e confiança próprias.
3. **Buscar na galeria do patch.** Manter os PNGs e IDs versionados do Data
   Dragon, filtrados pelo conjunto/modo ativo. Gerar várias referências leves
   por ícone (escalas, brilho e borda). Comparar interior normalizado, contorno
   e cor; agregar os escores e preservar alternativas quando ícones forem
   visualmente iguais. Uma rede pequena de *embeddings* pode desempatar o
   ranking, sem cabeça fixa de 193 classes. O processamento dos recortes e a
   busca rodam em Rust; se o encoder ajudar na validação, exportá-lo para ONNX
   INT8 e medir CPU e precisão antes de incluí-lo no instalador.
4. **Usar texto visível como confirmação.** Se o jogador passar o cursor sobre
   o item e aparecer uma dica com o nome, OCR lê esse texto e confirma o
   candidato visual. Isso gera rótulos revisáveis sem API de conta nem
   automatizar o mouse. A leitura normal continua possível sem tooltip.
5. **Rastrear eventos entre quadros.** Um ícone que desaparece do inventário e
   surge sob uma barra de vida gera hipótese de equipar; dois componentes
   desaparecendo e um item completo surgindo geram hipótese de combinação.
   O rastreador associa pela posição, aparência e tempo. Não transforma
   previsões próprias em rótulos de treino. Correções explícitas do jogador e
   texto legível podem alimentar o banco revisado.
6. **Processar apenas mudanças.** Hash e ocupação dos pequenos recortes são
   baratos. Recomparar ícones modificados, em lote, com cache limitado; nunca
   bloquear renderização da prévia, voz ou captura enquanto a identidade é
   calculada.

## Atualização de patch

Atualizar catálogo, imagens, receitas e manifestos de versão. Regerar as
referências/vetores a partir dos novos ícones. Só reentreinar o encoder se a
avaliação independente mostrar perda por mudança de arte ou interface. Dados
fixos de geometria, dados sazonais e registros confirmados ficam separados.
O Data Dragon pode ser publicado depois do patch; nessa janela conservar o
catálogo anterior com versão explícita e marcar ícones novos como desconhecidos.

## Validação antes de dicas específicas de item

Comparar RMS atual, galeria robusta e galeria com embeddings nos mesmos recortes
de partidas independentes, incluindo inventário, equipamentos, espaços vazios,
combinações, resoluções e escalas de interface. Medir precisão da identidade,
cobertura, falsa associação ao campeão e latência por quadro. Mostrar no app a
melhor hipótese quando útil, com incerteza explícita; dicas que nomeiam um item
ou campeão específico precisam da evidência correspondente. Dicas gerais de
economia e progressão não dependem desse reconhecimento.

## Implementação inicial

`tools/hm-item-native` calcula descritores de cor e borda e pesquisa uma galeria
de ícones do patch diretamente em Rust. `hm.item_visual_native` carrega a
galeria uma vez e envia ao Rust recortes das coordenadas originais da captura,
sem usar os pixels da prévia de 720p. O HUB registra três candidatos, margem,
concordância com o comparador RMS anterior e latência. `hm.item_movement`
registra hipóteses de transferência inventário → posição de tabuleiro em
quadros consecutivos. Nenhuma hipótese vira rótulo de treino ou comando de
equipar automaticamente.

Esta etapa ainda usa o comparador RMS anterior para localizar precisamente o
ícone dentro de cada espaço. OCR de tooltip, calibração de confiança e medidas
em partidas independentes continuam pendentes. O teste sintético de redução
da galeria de 193 artes para 23 px acertou 192 artes; isso mede somente
transformação dos PNGs oficiais, não a precisão do vídeo ao vivo.

O teste de integração abriu o HUB com 328 entradas de item (193 artes únicas),
processou um quadro de replay de 1920×1080 e manteve a captura desacoplada da
prévia. Nesse computador Linux, a inicialização do HUB levou 1,3 s e o quadro
levou 71 ms; a gravação testada usa outro patch, então esses números são apenas
de execução, não de acerto. A galeria nova tem cache limitado a 128 recortes.

Fontes: [Riot TFT Data Dragon](https://developer.riotgames.com/docs/tft),
[Prototypical Networks](https://arxiv.org/abs/1703.05175) e
[quantização ONNX Runtime](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html).
