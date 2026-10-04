# HM4.5: diagnóstico da sessão de 4 de outubro

Fonte: sessão `hm4-20261004-035734-676421`, especialmente `summary.json`,
`telemetry.jsonl`, `board-hub-observations.jsonl` e as 74 amostras PNG.
O usuário encerrou a sessão após 570,9 s; o arquivo foi selado sem erro de sessão.

## Onde os quadros se perdem

| Caminho | Observação |
| --- | ---: |
| Prévia recebida pelo aplicativo | 10.941 quadros, média de 19,2 fps |
| Prévia desenhada (estimativa de `preview_render` a cada 20 quadros) | cerca de 14 fps |
| Quadros antigos substituídos na fila da prévia | 975 |
| Quadros enviados à análise | 1.057, média de 1,85/s |
| Amostras PNG gravadas | 74; limite da coleta, não falha de captura |

A prévia configurada para até 30 fps não atingiu esse ritmo. O tempo de desenho
subiu: no primeiro minuto, o percentil 95 observado ficou perto de 10 ms; na
parte final, perto de 27 ms. A idade do quadro exibido também subiu, de cerca
de 46 ms para 111 ms no percentil 95 das amostras `preview_render`. Há perda
antes e durante o desenho; os registros não permitem atribuir toda a diferença
a uma única etapa. A prévia usa um caminho próprio no Windows, separado do
tráfego IP para análise na VM.

## Custo da análise e qualidade das leituras

| Etapa | Mediana | Percentil 95 | Máximo |
| --- | ---: | ---: | ---: |
| Inferência do mapa neural | 2,2 ms | 5,3 ms | 3.496 ms |
| Leitores, quadro até resposta | 220 ms | 939 ms | 7.936 ms |
| HUB, processamento | 679 ms | 6.141 ms | 20.886 ms |
| HUB, quadro até resposta | 977 ms | 8.230 ms | 22.749 ms |

O HUB é a operação individual mais longa, especialmente quando há ícones
equipados ou no inventário. Esses tempos são de parede e podem se sobrepor;
não são porcentagens de CPU. A voz F1 levou até 5,9 s para sintetizar uma frase
de teste, mas as sete falas solicitadas foram reproduzidas. Não houve narração
de dicas porque nenhuma dica acionável foi gerada: 59 esperavam decisão e 56
ficaram sem ouro confirmado. Nas leituras de decisão, unidades próprias ainda
não tinham identidade verificada. Em 99 de 102 observações do HUB a projeção
das posições ficou indisponível. Não há medição de RAM por processo ou da VM
para confirmar a hipótese de pressão de memória.

## Entropia observada

A entropia de Shannon da imagem em cinza, após reduzir as 74 amostras para
480 × 270, teve mediana de 6,99 bits/pixel nos primeiros 120 s e 7,41 após
300 s. Ela muda com a cena do replay e tem correlação fraca (r ≈ 0,16) com o
tempo de conversão BGRA→RGB nas amostras. Não há evidência de que uma elevação
da entropia visual seja a causa principal da queda de FPS. Essa medida descreve
a imagem, não a incerteza calibrada do classificador.

A incerteza de percepção, sim, é alta: ícones são apenas candidatos visuais e
as posições não são projetadas de forma confiável. Um par de quadros do próprio
teste conservou os dois recortes de inventário exatamente iguais. Por isso o
ranking de ícones recebeu um cache LRU de até 64 conjuntos de pixels; quadros
alterados são calculados novamente. Em um ensaio local com essas imagens, uma
observação repetida caiu de cerca de 309 ms para 37 ms, sem promover candidato
a item confirmado. Esse ensaio isolado não equivale a FPS medido no Windows.

## Correção incluída e próximo critério de campo

O instalador anterior podia reutilizar a distribuição `AgenteTFT-Core-v1` quando
o teste de saúde básico passava, mesmo que o pacote de catálogo e observador
tivesse mudado. O novo pacote usa `AgenteTFT-Core-v2`, mantendo a distribuição
anterior intacta. Assim o próximo teste efetivamente executará o novo código
e o escopo `set_plus_core` do catálogo.

No próximo teste Windows, verificar: versão e distribuição da VM em uso;
prévia sustentada perto dos 30 fps configurados; tempo e idade de renderização;
memória residente e privada do processo da HUD, agora registradas a cada 5 s;
tempos do HUB; geração de dicas apenas após unidades e ouro confirmados. A
otimização do ranking não elimina o custo da conversão e do desenho da prévia
em Tk. Uma solução de renderização acelerada ainda precisa ser implementada e
medida em campo antes de declarar a fluidez resolvida.
