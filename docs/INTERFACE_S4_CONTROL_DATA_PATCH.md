# S4 — corrigir os dados de interface sem criar outro leitor

Base: `ce50bb99aa470e6592c6fdde9c5c9f3c6be98adb` (S3).
Prioridade preservada: interface local completa; servidor e vídeos externos adiados.

## Evidência S3 recebida

40 JPEGs, 34 painéis, zero erros operacionais. O bloco completo das cartas ficou
igual ao S2: 113 pares nome/preço, 30 parciais, 23 desconhecidos, quatro vazios e
30 indisponíveis. Atualizar: 18 aparências observadas e 16 desconhecidas; 13
preços observados. Nas cinco aparências gratuitas reconhecidas, preço e contador
continuaram desconhecidos. Nada disso é acurácia ou autorização para ações.

## Causa geométrica inspecionada

No JPEG de 300000 ms, usando também o RGB decodificado pelo mesmo caminho FFmpeg:

- S3 `refresh_free_count`: `(483,1006,21,21)`, à direita do dígito e sobre parte
  do halo/seta; a caixa não enquadra o contador inteiro.
- S3 `refresh_price`: `(387,1043,18,23)`, cortando a esquerda do zero visível.

S4 usa respectivamente `(465,1012,19,20)` e `(379,1040,25,27)`. São dados do
perfil de UI, não valores esperados. O recorte do contador evita a seta vizinha.
Uma exibição que ultrapasse essas caixas continua sujeita a incerteza; a mudança
não demonstra suporte a qualquer escala/idioma/interface futura.

As assinaturas S3 foram extraídas com decodificação de imagem diferente da
conversão RGB do probe FFmpeg. Um ensaio geométrico local reproduziu diferenças
RGB suficientes para atravessar o limiar estrito em parte dos exemplos. Também
há aparência animada no botão. Isso não atribui todas as falhas à mesma causa.
S4 **preserva todos os templates anteriores** e acrescenta duas variantes da
classe gratuita usando os frames 250000/300000 já presentes no lote de sementes.
As variantes são geradas por `format=rgb24` antes do crop e amostragem inteira
idêntica à função Rust. Nenhum limiar é relaxado: similaridade >=0.95, MAE <=4
para atualizar, OCR >=0.70 e concordância 3x/4x continuam no mesmo binário.

## Patch herdado, não cópia do motor por temporada

`configs/ui/match001-shop-controls-v2-patch.json` contém apenas a identidade do
pai, duas caixas e referências de variantes. O pai é fixado por seu Git blob;
se mudar, o materializador recusa a atualização até nova revisão.

`training/shop_controls_profile.py` aceita somente alterações em regiões
numéricas existentes e variantes de classes já conhecidas. Rejeita sobrescrita
de limiares, idiomas, roster, valor esperado, classe nova por exclusão, duplicatas,
excesso de variantes e caminhos/hashes inválidos. O perfil efetivo é gravado
separadamente antes do probe; o perfil S3 nunca é sobrescrito.

As fontes dos templates fazem parte do manifesto congelado e são verificadas
antes/depois da decodificação. Até quatro pequenas regiões podem ser extraídas
pelo materializador genérico; esta configuração usa duas. Sem Pillow, outro OCR,
interpretação de prelabels, download ou treinamento. Os valores RGB derivados
são auditáveis, mas NÃO são rótulos numéricos nem evidência independente.

A topologia do tabuleiro, os pacotes sazonais e as definições futuras de
atributos/habilidades não são misturados a essa correção. Esses trabalhos
continuam na sequência loja -> banco/tabuleiro -> itens/painéis -> integração.

## Execução e validação

S4 reutiliza o executável release que produziu S3 em `rust/target/shop-s3`, e
confere seu hash contra o relatório anterior. **Não recompila Rust.**

O runner reutiliza `read_run`, `prepare`, `validate_controls` e o runner nativo
existentes. Compara o mesmo manifesto e as mesmas imagens, valida os traces,
confere hash de entradas antes/depois e exige igualdade completa das cartas e
das observações visuais de cadeado/XP. Preço de XP continua na comparação
numérica, pois o atlas tem novas dimensões; qualquer diferença é registrada.

O relatório separa `both_equal`, `candidate_only`, `baseline_only`, `both_disagree`
e `neither` por campo, com tentativas e geometria. Zero é valor observado,
nunca padrão. Ganhos não autorizam ativação. Contradição não é resolvida pela
confiança maior. Alteração nas regiões preservadas gera erro com evidência salva.

O teste nativo obrigatório cria PNGs sintéticos, mede equivalência da extração
RGB, gera um relatório S3 real e executa S4 com o mesmo binário Rust/FFmpeg/
Tesseract. Campos vazios não devem inventar números. Não é medição de precisão
dos números da gravação; a integração não utiliza respostas do usuário como labels.

O ambiente local possui FFmpeg/Tesseract, mas não Cargo; clone por Git falhou
por DNS. Foram inspecionados pixels e executado um ensaio OCR **limitado a uma
chamada** com um atlas de recortes para diagnóstico, não uma execução Rust S4.
Testes Python puros podem ser executados localmente; os testes integrados rodam
no CI. O resultado final de cada suíte deve ser registrado no PR.

```bash
bash scripts/probe_match001_shop_controls_v2.sh \
  "telemetry/data/match-001-shop-s3.8nV3K3Eh"
```

Pasta exclusiva `telemetry/data/match-001-shop-s4.XXXXXXXX`, com ambiente,
code-review e `evaluation/{plan.json,controls-effective.json,comparison.json,
report.json,run/}`. Enviar `SHOP4_SUMMARY`, `SHOP4_REGRESSION`, diferenças
relevantes e `SHOP4_REPORT`. Sem nova extração do MP4 ou rotulagem manual.

## Pendências não encerradas

Cadeado fechado sem referência real; sem catálogo/set/patch vinculados; sem
confirmação temporal de compra/refresh, associação com banco/tabuleiro, escrita
no GameState, ativação de perfil ou treino. Leituras persistentes do HP e sua
quarentena permanecem intactas. S4 corrige um perfil de UI, não completa o
HUD ou o autoaprendizado. A comparação real no Ubuntu ainda é necessária.
