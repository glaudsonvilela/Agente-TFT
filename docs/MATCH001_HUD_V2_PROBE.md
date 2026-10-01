# Match 001 — HUD v2 e probe curto

Continuação de `15db6adf2dbd4eaf4f0bc2c2d2f45a895d2839ef`, na branch
`work/match001-hud-v2-2026-10-01`. O layout v1, ROI event scan, GameState,
Opportunity Engine e pesos estratégicos permanecem intactos.

## Estado desta entrega

**Instrumentação de diagnóstico, não baseline visual aprovado.** O probe separa
correção de infraestrutura de acerto do OCR. Um CI verde não comprova accuracy
no replay. Nenhum Promotion Gate é aprovado por esta ferramenta.

O layout v2 deriva dos JPEGs 1920×1080 recuperados de
`TFT_MATCH_001_AI_BATCH.zip`. Foram inspecionados os recortes dos 40 frames, sem
usar OCR para escolher coordenadas. Valores esperados não escolhem caixas,
preprocessamento nem resultados de reconhecimento.

## Caixas medidas

Coordenadas em pixels, origem no canto superior esquerdo; intervalos semiabertos:

| Campo | x | y | largura | altura |
|---|---:|---:|---:|---:|
| stage (estágio 2 em diante) | 766 | 5 | 36 | 25 |
| gold | 1020 | 885 | 33 | 25 |
| level | 390 | 883 | 22 | 24 |
| xp | 466 | 884 | 49 | 20 |

O JSON usa um inset matemático de 1/8 pixel em cada borda antes da normalização,
para que o `floor/ceil` em f32 do `NormalizedRect` existente reproduza exatamente
essas caixas inteiras, sem expandir um pixel por arredondamento. Os testes Python
e Rust verificam as coordenadas efetivamente rasterizadas.

O nível exclui o prefixo `Nv.`; ouro exclui a moeda e o indicador de sequência;
XP mantém o texto completo `atual/necessário`, pois sua largura varia. O parser
retorna o numerador, conserva a barra na whitelist e rejeita frações inválidas.
Não se reduz `min_confidence=0.70` nem `ambiguity_margin=0.03`.

### Limitação visual descoberta: deslocamento do stage

Nos frames de 100000, 150000 e 200000 ms, o estágio 1 aparece mais à direita que
nos estágios seguintes. **A caixa compacta v2 acima não cobre esse layout inicial.**
Esses timestamps permanecem na amostra quando anotados; suas falhas entram no
denominador. Não escolher uma caixa usando o stage esperado, excluir esses
frames ou ampliar novamente a caixa para misturar os ícones com o texto.

Próxima correção: identificação visual do layout/âncora do HUD ou candidatos
geométricos medidos, com rejeição de ambiguidades. Isso requer validação separada;
o perfil v2 atual não deve ser promovido como solução completa de stage.

Frames sem HUD visível só entram no denominador dos campos realmente anotados.
Caixas para nível 10+, valores de ouro de três dígitos, outras escalas/resoluções
e outros replays ainda não foram validadas. HP continua dinâmico via player_list.

### Evidência de origem — SHA-256 dos JPEGs

- `0004_000150000ms.jpg`: `27569662dcf6c397d018926cfba0ff971ef8473275aabe8893e978a7901a2e65`
- `0006_000250000ms.jpg`: `828336ef0406f9b26bc2934b0a47421f6064de8d9077bc895598ce435db2afbd`
- `0011_000500000ms.jpg`: `dea88eb7653e0761beceb89e4d52f4a5641b057bb29d2db0e41200f7bd2d929a`
- `0025_001200000ms.jpg`: `39a27a0b4ec050c97eaaaa1b222b40f217a1ec03af1d31898f64b7ae4f687777`
- `0038_001850000ms.jpg`: `17c0d30a5ca0ed679e7e29cf36e5cc84cd56decce2d48459f924d2109ad2a943`

Os JPEGs completos não são adicionados ao Git. Os hashes tornam a referência
identificável, mas não significam que a execução verifique automaticamente o
hash do vídeo ou dos frames.

## Execução curta recomendada

```bash
bash scripts/probe_match001_hud.sh
```

O script usa apenas os JPEGs existentes e `prelabels.json` em
`training/annotations/match-001`, reutilizando o leitor Rust e Tesseract. Cria uma
pasta de evidências exclusiva em `telemetry/data/match-001-hud-v2.XXXXXXXX`, com
`report.json` e `events.jsonl`. Não reprocessa os 32 minutos, não substitui
`annotations.json` e não interfere no cliente do jogo.

Para buscar diretamente no vídeo somente os timestamps com labels humanos:

```bash
cargo run --manifest-path rust/Cargo.toml -p agente-tft-hud-replay-probe -- \
  telemetry/replays/match-001/TFT_MATCH_001.mp4 \
  configs/hud/tft-1920x1080-match001-v2.json \
  training/annotations/match-001/annotations.json \
  --output telemetry/data/match-001-human-hud-probe.json
```

`--output` recusa sobrescrever qualquer arquivo existente. Para usar sugestões
de IA, fornecer `--prelabels` explicitamente. Para ler os JPEGs em vez do vídeo,
acrescentar `--image-root training/annotations/match-001` (a raiz das anotações,
não a subpasta `frames`). O campo `image` é relativo a essa raiz; traversal e
symlinks existentes que escapem dela são rejeitados.

## Métricas e semântica

- Anotações: `exact_accuracy = correct / annotated`.
- IA não revisada: `prelabel_agreement`, com `exact_accuracy: null`.
- Sem expectativa para um campo: não entra no denominador.
- OCR desconhecido, confiança baixa e falhas de decode/leitura: continuam no
  denominador como incorretos; erros operacionais têm contador separado.
- Sem amostras para um campo: métricas nulas, nunca 100%.
- Confiança p50/p95: somente leituras aceitas, com contagem explícita; não é
  probabilidade calibrada de acerto. Percentil por interpolação linear.
- Sem consenso temporal nem propagação de estado entre timestamps distantes.
- O OCR é o `read_roi_robust` existente. A comparação acontece **depois** da leitura.

O probe verifica o nome-base de `source_video`, não a identidade criptográfica.
No modo JPEG, o vídeo não precisa existir no ambiente; o nome identifica a origem
declarada. O modo vídeo usa `ffmpeg -ss` antes de `-i`, como o extrator existente.
`timestamp_ms` é o timestamp solicitado/declarado; o PTS efetivo não é verificado
(`decoded_pts_verified: false`). JPEG e decode direto podem produzir pixels
diferentes por compressão; registrar o modo ao comparar relatórios.

Retorno 0: diagnóstico concluído, mesmo com OCR incorreto/desconhecido.
Retorno 2: relatório concluído com erros operacionais de decode/OCR.
Retorno 1: configuração/entrada inválida ou falha de saída. Nenhum retorno
significa aprovação dos gates de percepção.

## Testes

```bash
cargo test --manifest-path rust/Cargo.toml -p agente-tft-hud-replay-probe
python3 -m unittest discover -s training/tests -p test_match001_hud_v2.py -v
```

Incluem validação de fonte, schema, tipos, timestamps duplicados, zero legítimo,
separação de IA/ground truth, ausência de HP fixo, erro no denominador, parâmetros
não relaxados, parser PPM preservando bytes binários, paths, XP com fração,
caixas f32 e smoke test de seek com vídeo sintético vermelho/azul. O smoke
imprime SKIP quando FFmpeg está ausente. Unit tests não exigem Tesseract.

Depois: rodar o diagnóstico real; corrigir stage inicial; avaliar ROI →
preprocessing → OCR/confiança → consenso temporal. Só depois avançar para HP
via player_list, shop, board/bench e os demais itens do checkpoint.
