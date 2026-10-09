# Leitura do estágio e cadência do coach no laboratório Ubuntu

## Falha observada

Na sessão local `hm4-20261008-012720-581217`, o estágio foi aceito em 9 de 76
leituras. Uma captura de 1080p mostrava `3-1` nitidamente, mas o pré-processamento
numérico com borda produzia `3-1` a 3× com confiança 0,886 e `5-1` a 4× com
confiança 0,818. O leitor rejeitava os dois. A dica de preparação era a única
ação repetida e a primeira requisição de voz expirou.

## Alteração

O leitor Rust agora converte apenas o recorte fixo do estágio em escala de cinza,
sem borda, e exige concordância entre 1× e 2×. A mudança não depende do catálogo
de campeões nem de um patch. O coach também reconhece quando o nível planejado
já foi alcançado antes da rodada alvo e orienta a reconstrução da economia.
Essa orientação permanece uma hipótese baseada no HUD, não um resultado do
modelo neural nem um rótulo de treinamento.

## Verificação

* Nas cinco capturas com jogo visível guardadas da sessão anterior, a nova
  leitura retornou os estágios observáveis `2-7` e `3-1`; a sexta captura era
  a área de trabalho após o fim do vídeo e continuou sem leitura.
* Em nova captura de tela com o vídeo em 1080p, `hm4-20261008-013759-143624`,
  o estágio foi aceito em 60 de 64 leituras. A voz iniciou três dicas e não
  registrou erro. As leituras ainda renderam apenas duas ações distintas até
  a subida de nível; repetir a mesma ação não cria uma nova fala.
* Reavaliando as 64 leituras guardadas com a política nova, 35 quadros passaram
  do diagnóstico sem ação para o plano de economia após subir de nível.
* Na sessão local `hm4-20261008-014051-828626`, a dica "Você já está no nível 6
  antes da 3-2..." apareceu e a voz iniciou sua reprodução; a geração durou
  2,44 s e a idade do quadro ao iniciar a reprodução foi 2,86 s. A emissão
  física pelo alto-falante não foi medida.
* Os 38 testes Python do runtime e os quatro testes Rust do leitor de estágio
  passaram.

## Limite atual

No trecho observado, o tabuleiro ainda não ofereceu unidades verificadas para
recomendações de composição, posicionamento ou equipamento. Sem mudança
estratégica observada, o coach permanece quieto após falar a dica única;
preencher esse intervalo repetindo frases não acrescentaria uma decisão.
