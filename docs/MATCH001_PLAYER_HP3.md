# HP3 — enquadramento automático de texto, comparação em shadow

Base: HP2 (`47842a1877ff49ddf8da19d4ef72329618085b46`).

## Evidência recebida

HP2 do Ubuntu: 10 trechos, 80 frames, intervalos de 250 ms, 31 `accepted`,
3 `negative_display`, 35 `ocr_uncertain`, 2 `ocr_conflict`, 7 `badge_not_found`,
2 `badge_ambiguous`; 22 frames confirmados temporalmente; execução completa.

Nos trechos de 1050000, 1100000 e 1450000 ms as oito leituras de cada um ficaram
incertas. Repetir temporalmente não resolveu esses casos. No trecho de 1600000,
o leitor aceitou 36 antes do centro, mas retornou conflito no centro; o 56 do
JPEG original não reapareceu. Isso não prova correção: PNG do vídeo e JPEG
anterior não são os mesmos pixels. As duas representações devem ser avaliadas.

Esses trechos foram selecionados retrospectivamente para diagnóstico. Não
comparar sua proporção de accepted com a amostra esparsa como se fossem a mesma
distribuição ou usar a ausência de flags como prova de precisão.

## Candidato de preparação

O executável novo `player-hp-fit-probe` contém `HpTextFitOcr`, um adaptador opt-in.
O localizador HP1 permanece idêntico e encontra o mesmo marcador. Dentro do ROI
numérico encontrado, o adaptador:

1. calcula a projeção acromática já usada no HP1: `clamp(2*min(RGB)-max(RGB))`;
2. determina a união de TODOS os pixels acima de `max(100, 55% do máximo)`;
3. mantém essa caixa com margem de dois pixels, sem sair do ROI original;
4. entrega os pixels originais desse enquadramento ao MESMO preparo e Tesseract.

Não mantém apenas o maior componente: um sinal de menos separado também deve
participar da caixa. Não remove componentes, não interpola valores de HP e não
usa timestamps, nomes, expected ou labels para calcular a caixa. Os tons originais
dentro dela são preservados. A binarização só localiza a caixa, não substitui a
imagem entregue ao backend. As escalas continuam 3x e 4x, ambas >=0.70 e com
acordo obrigatório, conforme HP1.

Baixo contraste, foreground na borda do input, máscara inadequada ou caixa já
ajustada mantêm a preparação original. Geometria/buffer inválidos geram erro.
Os limites são fixos para esta candidata: ROI <=96x96 e trace limitado.

É uma heurística visual de enquadramento, não treinamento nem reconhecimento
universal. Traços muito fracos ainda podem ser excluídos pela localização da
caixa; os testes de sinal não garantem leitura de todo sinal possível. Por isso
este perfil não substitui o ativo nesta entrega.

## Comparação pareada

O frame é decodificado uma vez. HP1 e candidata o recebem com os mesmos pixels,
marcador e timestamp. Cada um tem seu próprio tracker. O relatório distingue:

- `both_readable_equal`;
- `both_readable_disagree`;
- `baseline_only_readable`;
- `candidate_only_readable`;
- `neither_readable`.

Readable inclui inteiros assinados aceitos; negativos continuam separados de HP
unsigned e de confirmação temporal. `candidate_only_readable` não é um acerto
comprovado, nem `baseline_only_readable` prova regressão semântica. Nenhuma
média de confiança ou maioria resolve divergências. O script imprime todas as
divergências e preserva os traces individuais.

Tempos medidos por leitor incluem busca + preparo + OCR, mas não decodificação;
o custo de rodar AMBOS não é anunciado como latência de produção.

## Reuso de evidência, sem novo vídeo ou rotulagem manual

```bash
bash scripts/probe_match001_player_hp_fit.sh "telemetry/data/match-001-player-hp2.AVJXEmYo"
```

Usa os PNGs e timestamps já extraídos pelo HP2, com conferência dos SHA-256.
Também executa o lote esparso original de JPEGs, inclusive leituras antes aceitas,
para não ocultar o caso 36/56. Os grupos `targeted_dense` e `sparse_regression`
permanecem separados. Não decodifica novamente os trechos do MP4, mas usa FFmpeg
para carregar as imagens existentes. No máximo 11 lotes/160 frames; um processo
novo por lote; timeout por lote mata o grupo inteiro de processos filhos.

Os manifests enviados ao nativo contêm apenas caminho, timestamp e hash.
Perfil, manifests e imagens são checados antes/depois. Saída em pasta exclusiva,
com relatórios por lote, eventos, hashes, tempos e motivos de ajuste. Nenhum
arquivo anterior é substituído. Os relatórios HP1/HP2 são referência histórica;
o baseline é EXECUTADO novamente, não copiado de estatísticas antigas.

## Validação e limites

Teste exploratório local: seis recortes JPEG antigos, Tesseract 5.5.0 e preparo
reproduzido em Python (Pillow/numpy). Alterar apenas PSM7 para PSM13 foi testado e
DESCARTADO por piorar os resultados nesses exemplos. Enquadramento por foreground
melhorou a disponibilidade em alguns exemplos, mas não resolveu todos. Esses
ensaios não são resultados do binário Rust ou validação independente.

O compilador Rust não está disponível no ambiente de edição. Testes Python
locais, testes Rust e integração nativa no CI são registrados no PR. O job HUD
media deve exigir o binário novo, FFmpeg e Tesseract; o teste nativo usa pixels
sintéticos com marcador/sinal para exercitar a preparação real, sem anunciar
acurácia para a fonte artificial. Medição completa nos 80 PNGs do usuário é
posterior ao CI; esses arquivos não estão no ambiente de edição.

HP1, OCR e perfil ativos não são alterados. Sem GameState, aprendizagem de pesos,
segundo OCR, promoção automática, ROI manual nova ou alteração em OpportunityWeights.
HP3 exercita uma candidata de preparação; o ciclo A1 completo com avaliação fora
da seleção e registry atômico ainda precisa ser integrado.

Referência técnica de preparação/segmentação: documentação oficial Tesseract,
https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html . A documentação apoia
avaliar margens e segmentação; não prova o ganho desta candidata no TFT.
