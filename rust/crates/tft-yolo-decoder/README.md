# Decodificador visual TFT em Rust

O modelo neural produz caixas e pontuações brutas. Este crate interpreta esse
tensor para o HUD de TFT: desfaz o redimensionamento com margens, mantém
limiares e limites por classe, aceita regiões da tela como evidência suave,
resolve caixas sobrepostas e guarda distribuições de identidade por objeto
rastreado. Isso permite trocar a configuração da tela sem reescrever a rede.

`hm/rust_yolo_decoder.py` carrega a biblioteca compartilhada e fornece as
caixas ao observador do software. Se a biblioteca não estiver no pacote,
continua disponível o decodificador Python atual. Para testar localmente:

```sh
cd rust
cargo test -p agente-tft-yolo-decoder --offline
cargo build -p agente-tft-yolo-decoder --release --offline
```

O decoder **não é um modelo treinável**. O treino de GPU atualiza os pesos
neuronais em um candidato separado; a promoção ao aplicativo exige avaliação
no vídeo e em recortes de partidas não usados no treino. Nenhuma predição
automática pode virar rótulo de treino.
