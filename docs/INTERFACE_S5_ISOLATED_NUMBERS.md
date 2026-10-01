# S5 — campos numéricos isolados e geometria por aparência

Base: S4, `1247cf9a5989859010285774be6f4432d81fca04`.
Mantém a prioridade de concluir a interface local antes de servidor/vídeos externos.

## Resultado S4 recebido do Ubuntu

40 frames; cartas completas e visuais de cadeado/XP inalterados.
Atualizar: 18 -> 27 aparências observadas; preço 13 -> 26;
contador gratuito 0 -> 14; preço XP permanece 30, mas com um ganho e uma perda.
Há sete aparências de Atualizar ainda desconhecidas em painéis localizados.
Disponibilidade não equivale a acurácia; as sementes incluem os frames avaliados.

Duas perdas de disponibilidade ficaram explícitas:
- 1200000 ms, XP: S3 4/4 elegíveis; S4 4/1 elegíveis, resultado desconhecido.
- 1450000 ms, Atualizar: S3 2/2 elegíveis; S4 4/4 com baixa confiança, resultado desconhecido.

Não copiamos o 4/2 do histórico nem escolhemos a maior confiança. Os logs mostram
que o campo XP mudou mesmo sem mudar seu recorte. A composição do atlas mudou;
isso é uma hipótese para a regressão, não prova de que versões externas foram iguais.
O código compartilhava todos os números no mesmo processo OCR por escala.

## Duas separações

1. `control_numbers.rs` executa um campo por imagem/processo. O número de XP
não recebe pixels do preço/contador de Atualizar e suas dimensões não dependem
desses campos. O caminho legado em `control_text.rs` permanece sem alteração.
S1/S2/S3/S4 continuam acessíveis com os mesmos argumentos; o sétimo argumento
opcional ativa S5.

2. `configs/ui/match001-shop-isolated-numbers-v1.json` descreve caixas por campo
e aparência. Atualizar ativo/escurecido reutiliza a caixa original S3; gratuito
usa as caixas S4. A seleção ocorre a partir da aparência antes do OCR, não a
partir do valor produzido. Nenhuma busca por timestamp ou número esperado.

Esse perfil não contém campeões, estatísticas, patch, respostas, confiança ou
novas classes visuais. Esquema estrito, cobertura de estados, limites de pixels
e ausência de sobreposição entre campos simultâneos são verificados em Python
antes de executar e em Rust ao iniciar. Coordenadas continuam no perfil UI,
separadas da topologia e dos pacotes sazonais.

## Reconhecimento e custo

Mesmo Tesseract, preparação gray/cubic, parser numérico e consenso S3.
Uma leitura requer 3x/4x concordantes, ambas >=0.70 por palavra. Zero precisa
ser lido; ausência, conflito e erro nunca recebem valores de catálogo.
Não há tentativas adicionais condicionadas ao resultado nem segundo modelo.

Há mais subprocessos: dois por campo elegível, máximo seis para controles,
mais as até duas chamadas das cartas. Um frame com XP e preço normal usa
quatro chamadas de controles; com contador gratuito usa seis. Painel ausente
não chama OCR. O custo fica no relatório e esta entrega NÃO promete ganho de
velocidade nem leitura a 60 fps. Otimização de execução contínua é distinta.

As tentativas e as caixas efetivamente escolhidas ficam nos campos. O validador
compartilhado refaz a seleção a partir da aparência e verifica chamadas/escalas,
confiança mínima e concordância, mantendo o comportamento legado sem a opção.

## Comparação de evidências

O preflight exige o relatório S4 completo/selado e o native report correspondente,
refaz as métricas S4 e verifica imagens, timestamps, perfil efetivo e demais
hashes históricos. Não recompila/sobrescreve o S3 congelado.

O executável S5 é compilado em `rust/target/shop-s5`. O wrapper reutiliza o
runner e validadores existentes, grava plano e hashes antes da leitura e
confere os arquivos novamente após ela. O perfil efetivo S4 é reaproveitado;
não cria novas sementes visuais nem extrai novamente o MP4.

Todos os controles visuais, incluindo Atualizar, e todo o bloco das cartas
precisam permanecer iguais ao S4. Números são comparados separadamente e todas
as perdas, novas leituras e divergências são preservadas. O S4 também não é
tratado como verdade. Nenhum resultado é promovido ou escrito no GameState.

## Testes e revisão

11 testes Rust do novo caminho: regras de UI, geometria, orçamento, campo ausente,
zero/contador, conflito, confiança, isolamento dos pixels XP, visuais inalterados,
reentrada indevida e erro de backend. 19 testes Python de política/traces.

Integração nativa obrigatória cria PNGs sintéticos, percorre S3 -> S4 -> S5 com
Rust/FFmpeg/Tesseract e verifica preço XP idêntico quando só outros controles
mudam, geometria por aparência, chamadas exatas, painel ausente, campos vazios,
cartas/visuais preservados e recusa de sobrescrita/relatório alterado. Não mede
acurácia no Match001 nem exige que o OCR reconheça o glifo sintético como label.

Os 19 testes Python passaram localmente, além de py_compile e sintaxe bash.
Sem Cargo no ambiente de edição; clone falhou DNS. Compilação/testes nativos
ficam para o CI, com resultados registrados no PR antes de merge. Não houve
nova execução de OCR real neste ambiente.

A revisão semântica desta entrega abrange os módulos alterados e seus contratos,
não todas as linhas de todo o projeto. A varredura estrutural da árvore continua
no CI/runner; os 22 apontamentos históricos não são automaticamente resolvidos.

## Ubuntu

```bash
bash scripts/probe_match001_shop_numbers.sh \
  "telemetry/data/match-001-shop-s4.FrfdWpYt"
```

Saída nova em `telemetry/data/match-001-shop-s5.XXXXXXXX/evaluation/`.
Enviar `SHOP5_SUMMARY`, `SHOP5_REGRESSION`, `SHOP5_DIFFERENCE` e `SHOP5_REPORT`.

## Próximos componentes

Após medir S5, avançar no vínculo de catálogo e loja/banco/tabuleiro sem inventar
lock fechado ou completar números incertos. Permanecem pendentes identidade
de set/patch, sequência temporal, itens/painéis de atributos e integração.
O requisito de dano, vida, defesa, habilidades e modificadores por campeão
continua no plano de dados sazonais/combate; S5 não implementa esses cálculos.
HP e sua quarentena, bancos A14–16, pesos e servidor permanecem intactos.
