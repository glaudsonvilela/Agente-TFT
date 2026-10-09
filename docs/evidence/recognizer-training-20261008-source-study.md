# Reconhecedor: fonte adicional e comparação congelada (08/10/2026)

Fonte de treino: partida Challenger do patch 18.3b, identificador público
`youtube:7DBW7owUjUA`. Mídia, recortes e modelos ficam somente no SSD em
`/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261008/spencertft-stage2-gamba-183b/`.
Esta fonte não integra a validação congelada do reconhecedor.

## Aquisição e rótulos

- Coleta de anotação a cada 2 segundos: 1.099 quadros e 7.905 recortes de unidades.
- Minerador esparso: 7 propostas de transição de loja, 0 rótulos ouro.
- `scripts/densify_shop_transitions.py` reexaminou as sete janelas a 250 ms;
  nenhuma ganhou identificação inequívoca por loja, banco e OCR. As propostas
  continuam sem rótulo. A ocultação do banco por tooltip é uma causa concreta
  observada nos quadros de Cinderling.
- Tooltip de Leona reexaminado a 250 ms: 12 recortes candidatos em uma janela
  curta. A adjudicação aceitou 7 com professores mistos e isolou 5 por
  discordância. Os sete recortes pertencem à **mesma jogada**, portanto não
  equivalem a sete partidas ou fontes independentes.
- Um segundo tooltip de Aphelios permaneceu abaixo do limiar de OCR e não
  gerou rótulos.

## Treino e comparação justa

O braço novo recebeu apenas os 7 recortes aceitos de Leona e começou da
cabeça congelada `optimizer-default-parity`. Ambos foram avaliados nas mesmas
32 imagens de validação, distintas da fonte nova. O motor de decisão Rust não
participa desta comparação.

| Modelo | Acertos | Macro-revocação | Entropia cruzada |
|---|---:|---:|---:|
| Baseline | 21/32 | 0,6893939394 | 3,1966182142 |
| Com Leona | 21/32 | 0,6893939394 | 3,1979695261 |

Pelo critério prévio (macro-revocação, depois menor entropia), o baseline foi
retido. **A validação contém 22 classes, mas nenhuma imagem de Leona**. Logo,
esse 21/32 só mede regressão geral; não mede o ganho específico procurado.
No teste histórico havia três Leona, e ambos os modelos acertaram duas; esse
teste não participou da seleção e é pequeno demais para provar generalização.
Não houve promoção ao HUD nem evidência de melhora geral. Resultado
privado: `leona-challenger-20261008/autonomous-challenger-selection.json`.

## Próximo dado necessário

O gargalo medido é identidade verificável e diversidade de fontes, não volume
de quadros. Para melhorar outras classes, buscar eventos em partidas distintas
que liguem nome explícito ao recorte sem ambiguidade de seleção, validar em
fonte separada **com as classes alvo representadas**, e manter hipóteses não
confirmadas fora do treino. Não repetir
as mesmas cenas como se fossem novas amostras independentes.
