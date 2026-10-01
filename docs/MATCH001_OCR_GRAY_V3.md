# Match001 — OCR numérico v3 (candidato, opt-in)

Continuação do `4bda4fb3d5d2cfe62a7307ea91874365744813fb` / PR #7.
Branch: `work/match001-ocr-gray-v3-2026-10-01`.

## Evidência recebida do Ubuntu

Execução v2: `telemetry/data/match-001-hud-v2.pfj6GDxL/report.json`.
Fonte desta tabela: resumo e timestamps enviados pelo usuário, não uma nova
execução feita pelo editor. Métrica: **concordância com prelabels de IA**.

| Campo | Anotados | Concordantes | Reconhecidos divergentes | Unknown |
|---|---:|---:|---:|---:|
| gold | 35 | 14 | 0 | 21 |
| level | 35 | 29 | 2 | 4 |
| stage | 38 | 33 | 0 | 5 |
| xp | 35 | 1 | 0 | 34 |

Level: em 1400000 e 1900000 ms, esperado 8, OCR 3, confiança 0.7473866.
Os recortes reais recuperados mostram o 8 nesses pontos. Gold: a borda da moeda
entra na caixa do número em alguns valores de um dígito. Apertar a esquerda por
uma constante também pode cortar o primeiro caractere de valores de dois dígitos.
As caixas não são ampliadas nem deslocadas nesta entrega.

Stage: três unknowns iniciais (100000, 150000, 200000 ms) coincidem com o layout
inicial deslocado já documentado. Os outros dois (1100000 e 1550000 ms) NÃO são
explicados por esse deslocamento inicial; ficam pendentes de diagnóstico separado.

## Alteração nativa mínima

`HudOcrEngine::prepare_roi` tem implementação padrão idêntica ao processamento
anterior. Ambos os leitores existentes a usam. O robust reader, os parsers, os
pesos estratégicos e os filtros de confiança não foram reescritos.

`TesseractOcr::default()` permanece legado. Somente o opt-in
`with_numeric_gray()` / CLI `--numeric-gray` habilita, para gold/level/xp:

1. Tons de cinza sem binarização antecipada. Para gold apenas, projeção acromática
   contínua `clamp(2*min(R,G,B)-max(R,G,B),0,255)` atenua a moeda amarela e preserva
   texto neutro. Não usa o valor esperado, timestamp ou posição de componentes.
2. Contraste do helper existente, interpolação cúbica Catmull-Rom e uma borda
   sintética de 10 pixels. A borda não captura área adicional da tela.
3. Texto escuro sobre fundo claro e PSM 7 (linha). Duas tentativas: 3x e 4x,
   ambas invertidas. A política continua `min_confidence=0.70` e
   `ambiguity_margin=0.03`.
4. XP de fração completa exige uma barra válida. Sem ela, retorna unknown em vez
   de interpretar `010` como o inteiro 10. O parser legado de XP inteiro continua
   disponível fora deste perfil.

As quatro ROIs são numericamente iguais às do v2. Stage mantém também sua
política e seu backend antigos. HP não foi adicionado. O v3 é perfil de diagnóstico
no probe; ele NÃO é ativado automaticamente no runtime ou nos demais aplicativos.

A preparação valida stride, buffer, formatos RGB/RGBA/BGRA e escala 1..8, com
limites de pixels antes da alocação da saída. Não há novas dependências externas
Rust: apenas referência ao crate capture-core já existente.

## Validação e limites

Cinco testes Python verificam caixas preservadas, stage inalterado, ausência de
HP, confiança congelada, tentativas limitadas e runner não destrutivo.
Os novos testes Rust cobrem preparação substituível, confiança, interpolação,
projeção de cor, stride, polaridade, perfil opt-in e rejeição de XP sem barra.

O workflow adicional `HUD media` instala FFmpeg e Tesseract/eng antes dos testes.
Exige o smoke real do processo Tesseract e exercita o seek sintético existente.
O smoke Tesseract usa imagem branca: valida execução/IO, NÃO accuracy numérica.
O CI completo existente permanece obrigatório antes do merge.

Houve um ensaio exploratório local, em uma única chamada Tesseract, de 12 recortes
(4 timestamps x 3 campos) com um protótipo Pillow/cubic, inversão e PSM 7. Os textos
de XP e os 8s motivaram a implementação. O ensaio NÃO inclui a projeção de gold
final e NÃO é execução do pipeline Rust final: não deve virar uma métrica v3.

**O lote completo com o binário Rust v3 ainda deve ser medido no Ubuntu.**
Maior concordância neste replay de calibração não prova generalização nem aprova
Promotion Gate. Leituras erradas/unknown permanecem no denominador. Não há correção
automática de labels, consenso temporal entre frames distantes, ou escolha de
preprocessamento pelo valor esperado. Fonte/PTS continuam com as limitações do v2.

## Próximo comando

```bash
bash scripts/probe_match001_hud_v3.sh
```

Usa os mesmos JPEGs e `prelabels.json`, sem percorrer o vídeo. Cria uma pasta
exclusiva `telemetry/data/match-001-hud-v3.XXXXXXXX`, com `report.json`,
`events.jsonl`, stderr e ambiente (commit, versão Tesseract, SHA-256 de layout e
prelabels). Os hashes registrados não verificam a identidade do vídeo/JPEGs.
Cada registro identifica o perfil realmente aplicado; stage mostra legacy_binary.
O runner imprime também todas as divergências reconhecidas por campo.

Para repetir o controle antigo, `bash scripts/probe_match001_hud.sh` continua
inalterado. Compare os mesmos timestamps, labels, modo JPEG e versão de Tesseract.

## Referências de processamento

Documentação primária consultada para polaridade, borda e segmentação:
- https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
- https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html

A projeção acromática de gold e os limites de recursos são decisões deste projeto,
não resultados garantidos pela documentação de Tesseract.
