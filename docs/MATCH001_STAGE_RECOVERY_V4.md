# Match001 — recuperação limitada de stage e rastreio de tentativas (v4)

Base: `9be47c156e9feaca6fab74004b7ec89f8be31316`, PR #8.
O PR #9 permanece alternativa separada: não foi integrado.

## Medição recebida, não executada novamente pelo editor

O usuário executou `numeric_gray_v3`, com saída 0 e 38/40 frames selecionados.
São 143 comparações campo/timestamp contra **prelabels de IA**, não 143 frames
independentes nem ground truth humano. Resultado: gold 34/35; level 35/35;
xp 35/35; stage 33/38. Nenhuma divergência reconhecida; seis unknowns.

O `environment.txt` enviado registra o commit acima, Tesseract 5.3.4 e:

- layout v3 SHA-256: `06927dc632141dc157cb8f4036ca46b2ed44a7c093adcc39514970628856cbb4`;
- prelabels SHA-256: `13f27962aedae3c9ac266f2f0476778f6eb0780d2bdb0e5a53e7ce21491d6d77`.

Isso identifica a execução declarada; não é auditoria do binário no PC.
Relatório local: `telemetry/data/match-001-hud-v3.obhcnaYO/report.json`.
Gold unknown: 850000 ms, esperado 44. Stage unknown: 100000/150000/200000,
1100000 e 1550000 ms, esperados 1-1/1-3/1-4/3-7/4-7.

## Inspeção e escopo

Os JPEGs do AI batch foram recuperados e inspecionados visualmente.
Três textos iniciais estão fora da caixa padrão. Os dois tardios (3-7/4-7)
estão dentro dela. Não se atribuem as cinco ausências ao mesmo deslocamento.
O 44 está visível no recorte de gold. O resumo v3 não revela a causa de rejeição.

Foi feito um único batch exploratório externo (33 recortes processados), com
protótipo NumPy/Catmull-Rom, Pillow e **Tesseract 5.5.0**, PSM 7, whitelist
`0123456789-`. Testou duas posições de stage e escalas 3x/4x, além de 3x/4x/5x
para o gold pendente e dois controles. Nos recortes selecionados, o stage em
cinza foi reconhecido nas posições visíveis. O gold 44 produziu leituras com
confianças diferentes entre escalas; a ausência do PC não foi reproduzida.

**Esse ensaio não é execução do binário Rust, nem métrica do v4.** Além da versão,
o decoder e a whitelist de gold diferem do pipeline. Não se escolheu uma nova
escala de gold a partir desse experimento: gold/level/xp continuam exatamente v3.

## Implementação

Opt-in do probe: `--numeric-gray --stage-recovery <candidates.json>`.
O runner v2, o runner v3, seus layouts, o backend e os pesos permanecem intactos.
O código de recuperação fica isolado no aplicativo, não no runtime de jogo.

1. Executa o leitor v3 original uma vez, com a mesma política e as mesmas ROIs.
   Rastreia as chamadas existentes de preparação/OCR, sem duplicá-las.
2. Se houver leitura aceita, mantém o resultado, mesmo se ele discordar do label.
   Só `Stage` com status `unknown` sem erro operacional pode usar a recuperação.
   Gold/level/xp nunca usam fallback nesta entrega.
3. Para stage desconhecido, testa duas caixas compactas medidas, cada uma em
   3x e 4x com tons de cinza. Reutiliza a preparação neutra de v3 e a whitelist
   de **stage** (PSM 7); não usa o parser ou a whitelist de nível.
4. Exige hífen literal válido e concordância de duas escalas da **mesma caixa**,
   ambas passando a confiança mínima existente. Qualquer valor elegível
   conflitante, mesmo vindo da outra caixa, faz o resultado permanecer unknown.
   Não escolhe caixas por timestamp ou valor esperado. As duas escalas NÃO são
   evidências temporais independentes; a confiança reportada é a menor delas.
5. Erros de backend/preparação da recuperação permanecem erros operacionais,
   com os detalhes preservados; não viram acerto nem desaparecem do denominador.

| Candidato | x | y | largura | altura |
|---|---:|---:|---:|---:|
| standard | 766 | 5 | 36 | 25 |
| initial | 826 | 5 | 36 | 25 |

Caixas não são unidas/alargadas; a posição inicial é uma alternativa explícita.
O inset de 1/8 pixel mantém a rasterização f32 igual às medidas. Há limite de
1..4 candidatos, caixas compactas e resolução exata. O arquivo fornecido tem 2.
A política de stage deriva do layout v3: confiança 0.70, margem 0.03. A rejeição
adicional de conflitos é mais conservadora, não relaxa esses filtros.

## O que o trace informa

`attempt_trace` contém configuração, dimensões, texto devolvido pelo backend,
confiança, valor parseado e razão: `candidate`, `below_min_confidence`,
`domain_invalid`, `no_text_or_backend_filter`, `backend_error` ou `preprocess_error`.
O nome `no_text_or_backend_filter` é intencional: o backend pode já ter filtrado
um texto e retornado None; o observador não inventa o conteúdo descartado.
Valores de diagnóstico não substituem o resultado do robust reader.

Recuperações retêm `primary_read`, `recovery_candidates`, `selected_candidate`,
`recovery_reason`, `recovery_applied` e contagem total de chamadas. Os registros
finais continuam um por campo/timestamp, sem multiplicar o denominador.
`temporal_consensus=false` e Promotion Gate não avaliado permanecem explícitos.

## Execução no Ubuntu

```bash
bash scripts/probe_match001_hud_v4.sh
```

Usa os mesmos JPEGs e prelabels e cria pasta exclusiva
`telemetry/data/match-001-hud-v4.XXXXXXXX`. Não sobrescreve anotações ou relatórios.
Imprime resumo, WRONG, UNKNOWN, STAGE_RECOVERED e HUD_PENDING_TRACE. O gold 850000
ms, caso continue unknown, já terá suas duas tentativas exibidas nessa saída.
Não exige outro bloco manual para procurar o timestamp.

O ambiente inclui commit, estado dos arquivos rastreados, versões, hashes de
layouts, prelabels e JPEGs locais. Os hashes são inventário, não verificação do
vídeo nem prova do PTS; continuam as limitações de identidade/tempo do v3.
Não executar com código local modificado sem revisar o ambiente gravado.

## Validação

Quatro testes Python locais passaram, incluindo runner com backends simulados,
pastas exclusivas, inputs preservados e propagação de saída 2. `bash -n` passou.
Os testes Rust adicionados cobrem recuperação, rejeição de conflitos, ausência
de hífen, confiança baixa, proteção de campos numéricos, resultado independente
dos labels, erros operacionais e rasterização das duas posições.

Rust não está instalado no ambiente de edição. Compilação/testes Rust devem
ser confirmados no CI antes de merge; resultados ficam registrados no PR.
Ainda é necessário medir o lote v4 no Ubuntu 5.3.4. Não existe taxa de acerto v4
aprovada nesta entrega. Depois: outros frames/partidas, ausência de HUD, revisão
humana e comportamento temporal antes de qualquer promoção de percepção.

Referência primária de processamento/PSM/bordas:
https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
