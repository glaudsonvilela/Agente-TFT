# Itens no vídeo ao vivo: diagnóstico e recuperação

## Causa encontrada

Na sessão Ubuntu `hm4-20261008-014420-169559`, o HUB local tinha 0 imagens de
itens disponíveis, embora o catálogo visual selecionasse 328 entradas. A
biblioteca Rust de comparação também não estava no pacote do MVP. A rede ONNX
gerava hipóteses para o inventário, mas elas não passavam por confirmação visual
e nenhum item equipado recebia nome. A ausência dos dois componentes era do
empacotamento Ubuntu, não do vídeo.

## Alteração

O inicializador Ubuntu agora verifica a referência do catálogo, conecta a
galeria de imagens existente no SSD e inclui a biblioteca Rust. O HUB compara
o primeiro candidato da arte do patch com o descritor Rust e, no inventário,
também com a cabeça neural. Concordância produz apenas um candidato nomeado.
Conflito conserva o espaço como incerto. A persistência entre quadros usa essa
reconciliação. Sem dados de atributos para um emblema, o nome visual continua
visível e a ligação aos atributos permanece explícita como ausente.

O processo local limita a uma thread as pequenas multiplicações da galeria;
isso reduz disputa com a prévia de vídeo. A regra também vale ao iniciar o
runtime Windows.

## Evidência do teste

* Reprocessando a captura `000002332` da sessão do usuário, a galeria encontrou
  Espada G.p.C. e Cinto do Gigante no inventário. Bastão Desnecessariamente
  Grande apareceu na arte e na rede neural, mas o comparador Rust preferiu
  Colete Espinhoso: o resultado foi mantido como conflito.
* Reprocessando `000000588`, dois itens equipados tiveram concordância entre
  a arte e Rust: Capa de Fogo Solar e Emblema de Defendente. O emblema possui
  apenas ID visual no catálogo estruturado carregado.
* Na nova sessão de captura da tela `hm4-20261008-015458-469549`, a galeria
  carregou 328 ícones e o comparador Rust ficou ativo. Nos 13 resultados do
  HUB com o vídeo visível, houve dois nomes concordantes no inventário por
  resultado e de um a dois itens equipados nomeados. O espaço em conflito
  permaneceu sem ID promovido.
* Repassando as 42 observações gravadas pela persistência entre quadros, 58
  candidatos do inventário e 33 candidatos equipados alcançaram duas leituras
  concordantes. Quando a casa do tabuleiro não foi localizada, o item equipado
  aparece pelo nome sem posição atribuída. O marcador visual pode trocar de ID
  ao longo do vídeo, e a contagem recomeça nesses casos.
* Em amostras gravadas com os ícones ativos, o processamento do HUB teve
  mediana de 646 ms e pico de 1.400 ms. Um ensaio local com uma thread BLAS
  processou duas capturas novas em 280 e 332 ms e uma captura repetida em
  39 ms. Ainda falta medir a prévia de vídeo após essa mudança em Windows.

## Limite

Os nomes são candidatos apoiados por dois ou três leitores. Não são rótulos
de treinamento nem autorizam sozinhos uma sugestão para equipar: falta ligar
com segurança o item ao campeão e à posição no tabuleiro. A rede de itens
atual lê o inventário; para equipados, a confirmação é feita por arte e Rust.
