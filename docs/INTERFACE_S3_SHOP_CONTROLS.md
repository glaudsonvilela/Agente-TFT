# S3 — controles visuais da loja, mantendo as leituras S2

Base: S2, commit `303a20e76ddae726b50603472c6d3797da282384`.
Prioridade: terminar a interface local antes de servidor e vídeos externos.

## Resultado S2 recebido

O log do Ubuntu registra 40 frames, 34 painéis localizados, 113 pares nome/preço,
30 leituras parciais, quatro marcadores de vazio, 23 desconhecidos e 30 espaços
indisponíveis. S1 tinha 29 painéis e 84 pares. A comparação do mesmo lote não
registrou perdas ou divergências nos campos previamente aceitos: 38 novos nomes
e 30 novos preços. Isso é disponibilidade operacional, não acurácia.

As duas referências estruturais recuperaram os painéis em 250000, 1200000,
1250000, 1700000 e 1850000 ms. Os conflitos TSV ficaram locais aos campos.
S2 continua sem catálogo vinculado, consenso temporal ou escrita no GameState.

S3 não abre outra rodada de calibração dos nomes: acrescenta os controles.

## Aparência não é permissão

O perfil `configs/ui/match001-shop-controls-v1.json` contém assinaturas RGB dos
ícones do cadeado, comprar XP e atualizar, fora das cinco cartas. O leitor usa
`visual-match` existente e exige simultaneamente similaridade estrutural >=0.95
e erro médio RGB dentro do limite do perfil. A diferença RGB evita que a
normalização de contraste, sozinha, confunda uma versão colorida com a cinza.
Os limites não são probabilidades calibradas.

Estados observáveis:

- cadeado: aparência aberta;
- comprar XP: aparência ativa ou escurecida;
- atualizar: aparência ativa, escurecida ou de atualização gratuita;
- qualquer controle: desconhecido, ambíguo ou indisponível.

O contrato admite uma referência de cadeado fechado, mas o perfil entregue NÃO
inclui uma: ela não foi observada no lote usado para as sementes. Não reconhecer
o ícone aberto não significa que esteja fechado. `lock_state` permanece falso
no resumo; `lock_appearance` indica somente a nova capacidade visual parcial.

Duas classes simultaneamente elegíveis produzem ambiguidade, sem escolher a de
maior score. Painel não localizado torna os controles indisponíveis, mesmo que
um recorte isolado se pareça com a referência.

`action_allowed` permanece null para todos: aparência ativa não comprova saldo,
regra de fase ou autorização do cliente. Nenhum clique ou comando é enviado.

## Preços e contador

O preço de comprar XP, o preço de atualizar e o contador de atualizações gratuitas
são lidos dos pixels com o mesmo Tesseract, preparação gray/cubic e funções de
concordância existentes. Não há preços 4/2 embutidos como respostas.

Uma imagem pequena por escala reúne os campos numéricos elegíveis. As escalas
3x e 4x precisam concordar, com confiança mínima por palavra >=0.70. Zero é um
valor possível, diferente de ausência. O contador gratuito só é tentado quando
a aparência gratuita foi reconhecida; preço zero não inventa quantidade de usos.

O rastreio de roteamento mantém índices na ordem de `numeric_fields`:
`buy_xp_price`, `refresh_price`, `refresh_free_count`. Conflitos de coordenadas
não são distribuídos aos outros campos. Se um controle não foi reconhecido,
sua leitura numérica fica `not_observed`, sem reutilizar dados antigos.

O custo é explícito: até duas chamadas OCR adicionais por frame, além das até
duas das cartas. `controls_ocr_process_calls` e `total_ocr_process_calls` ficam
separados. Os tempos desta rodada incluem controles; não são benchmark direto
contra S2. Não existe outro modelo/backend nesta entrega.

## Isolamento e manutenção

As sementes visuais vieram de recortes dos frames 150000, 250000, 300000 e
1250000 ms; caminhos e hashes ficam no perfil. São exemplos de desenvolvimento
do mesmo replay, não referências independentes de avaliação.

A estrutura lógica continua em `configs/topology`, aparência/pixels em
`configs/ui`, vínculo da gravação em `configs/contexts` e dados sazonais em
`knowledge/releases`. Nenhum campeão, custo de catálogo ou patch escolhe o
estado dos controles. Uma atualização de catálogo não reescreve suas caixas.

Os índices visuais são construídos uma vez, antes dos frames. As funções de
leitura/concordância de S2 são reutilizadas; em `screen.rs`, somente sua
visibilidade Rust foi ampliada para o novo módulo, sem mudar o algoritmo.

A CLI conserva S1 com quatro argumentos e S2 com cinco. O sexto argumento
opcional acrescenta controles ao mesmo frame decodificado. O bloco `read` das
cartas fica intacto; `controls` é um bloco irmão no relatório.

## Evidência e regressão

O runner verifica previamente o relatório S2 selado, as mesmas imagens/timestamps
e hashes de UI/recuperação. S3 salva saídas novas, sem sobrescrever evidência,
base de dados ou executáveis congelados. O target de build é `rust/target/shop-s3`.

A validação Python refaz as decisões visuais e numéricas a partir dos traces e
confere permissões nulas, ausência, limites de chamadas e falta de confirmação
temporal. Limiares são convertidos para f32, como no Rust, evitando uma falsa
rejeição exatamente na fronteira causada pela representação numérica do Python. Comparação final exige igualdade do bloco completo de leitura S2,
incluindo scores e tentativas, excluindo apenas o tempo total externo ao bloco.
Divergência encerra com erro e mantém o relatório para análise, sem forçar
igualdade ou atribuir a causa ao novo leitor. Ambientes diferentes podem afetar
os resultados de OCR; o relatório histórico não é benchmark simultâneo.

## Testes

Doze testes Rust cobrem compatibilidade, geometria, assinatura, ambiguidade,
RGB/BGRA/stride, ausência de referência fechada e concordância numérica.
Treze testes Python cobrem a validação dos traces. Um teste nativo obrigatório
no HUD media cria PNGs sintéticos, roda S2 e S3 com Rust/FFmpeg/Tesseract e verifica
cartas inalteradas e aparências distintas. Os campos numéricos em branco não
podem produzir preços padrão. Esse teste não mede precisão dos números reais.

Os treze testes Python passaram localmente; não há Cargo no ambiente de edição.
Uma tentativa de clone local falhou por DNS. A inspeção visual e análise de
assinaturas no lote não são execução do binário Rust nem acurácia. CI e teste
nativo devem passar antes do merge, com os resultados registrados no PR.

## Execução Ubuntu

```bash
bash scripts/probe_match001_shop_controls.sh \
  "telemetry/data/match-001-shop-s2.ajpkjU0P"
```

Saída em pasta exclusiva `telemetry/data/match-001-shop-s3.XXXXXXXX`:
`SHOP3_CONTROLS`, `SHOP3_SUMMARY`, `SHOP3_REGRESSION` e `SHOP3_REPORT`.
Reutiliza os 40 JPEGs, não percorre MP4 e não exige anotações humanas.

## Pendências preservadas

Ainda faltam referência fechada do cadeado, medição real dos novos controles,
identidade sazonal compatível, integração temporal e associação de compras com
banco/tabuleiro. Os 23 desconhecidos e 30 parciais do S2 não foram corrigidos por
acrescentar controles. O histórico HP e sua quarentena permanecem inalterados.
S3 não escreve GameState, promove perfis, treina modelos ou conecta servidor.
