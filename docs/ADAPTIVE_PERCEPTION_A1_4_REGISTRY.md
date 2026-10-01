# A1.4 — registro persistente de perfis e bloqueios

Base: HP5, commit `81492c49f6f2c83961e3c8aa35b67aabe34cc47b`.

## Decisão após a medição HP5

Resultado enviado do Ubuntu: 96 frames em três sequências, 59 leituras aceitas
por cada leitor, 58 pares aceitos iguais, uma leitura exclusiva de cada lado,
56 confirmações temporais por leitor. Não houve vantagem líquida de
 disponibilidade nesta amostra. O HP3 havia melhorado a amostra dirigida,
mas isso não justifica a substituição geral do HP1. Quarentena herdada do HP4
permanece; `retain_baseline` não estabelece correção semântica do baseline.

Na sequência 21–29 s, ambos retornaram `badge_not_found` nos 32 frames; foram
registrados 16 checksums repetidos. O log não determina a causa da ausência,
nem comprova travamento da captura. Esses frames não são excluídos para
melhorar a métrica. Não chamar repetição temporal de evidência independente.

A rodada comparativa dessa candidata termina sem promoção. Não há novo ajuste
de OCR ou procura de mais exemplos favoráveis nesta entrega. Passamos a uma
peça que faltava ao ciclo adaptativo: memória operacional durável.

## Entrega

`training/perception_registry.py` implementa um registry local em SQLite,
com snapshot versionado e histórico de eventos na MESMA transação:

- identidade por tipo do leitor + SHA-256 do executável + SHA-256 da configuração;
- referência do baseline separada por gravação/subsistema/campo;
- evidências identificadas por conteúdo: repetir a importação não duplica eventos;
- bloqueios anexados com suas origens, sem apagá-los por uma avaliação posterior;
- revisão monotônica e compare-and-swap opcional para alterações concorrentes;
- verificação do checksum do snapshot e da cadeia de eventos ao reabrir;
- corrupção, esquema desconhecido e banco de outra aplicação causam erro,
  nunca reset automático;
- consulta de permissão: quarentena permite diagnóstico shadow, NÃO ativação.

Um leitor com bytes diferentes recebe outra identidade e começa sem aprovação.
Renomear o arquivo de origem não altera a identidade dos bytes. O tipo do leitor
é identidade de comportamento, não um nome de exibição editável. Mesmo uma
identidade desconhecida ou recém-registrada NÃO pode ativar perfil nesta versão.

O banco guarda metadados/avaliações/bloqueios, não pesos treinados ou respostas
corretas de HP. Limites iniciais: 2.000 revisões e snapshot de 8 MiB, com erro
explícito ao exceder. Este registry não está no caminho por frame do motor Rust.

## Importação do HP5 sem repetir OCR

`training/register_hp5_profiles.py` verifica primeiro os relatórios e só depois
abre o banco. Reutiliza `source_context`, `build_review`, `review_batch`,
`check_sequence` e `inherited_decision` dos módulos HP4/HP5 já existentes.

Exige COMPLETE.json e os hashes de plano/relatório; verifica novamente os
fingerprints do histórico, executável/configuração; reconstrói a decisão HP4;
confere manifests, PTS, confirmações, relatórios por sequência e agregados HP5.
Não confia apenas no campo `quarantine` ou no resumo colado no terminal.

Vídeo/imagens não são abertos nesta etapa. Os hashes de mídia são referências
registradas, não uma revalidação atual dos pixels. Patch/set continuam `null`;
não se inventam versões ausentes. Executável/configuração são rehashados, mas
isso não estabelece identidade completa das bibliotecas dinâmicas/traineddata.

Após commit, o comando fecha e reabre uma conexão para consultar os bloqueios
persistidos. Saída `restart_read_verified` significa essa nova conexão, não
um teste de reboot/power-cut no PC do usuário.

## Execução no Ubuntu

```bash
bash scripts/register_match001_perception.sh \
  telemetry/data/match-001-player-hp5.TP4E2p1M
```

Também aceita `run/report.json`. Reutiliza o binário HP3 somente para hashing,
sem executá-lo ou recompilá-lo. Mantém o override `TFT_HP5_PROBE` do runner HP5.
Destino persistente (não uma nova pasta descartável a cada execução):

```text
telemetry/data/perception-registry/registry.sqlite3
```

Imprime `A14_REGISTRY` e `A14_SUMMARY`. Para os dados reportados, a candidata
deve permanecer `quarantined`, com `activation_allowed=false`. Uma segunda
importação idêntica deve retornar `changed=false`, sem aumentar a revisão.

## Limites e próximo bloco

Isto NÃO é treinamento automático, nem ativação/rollback de perfis em produção.
Não escreve active.json, não conecta o leitor ao registry por frame, não muda
GameState, OpportunityWeights, ROIs, thresholds, backends ou regras.
A referência de baseline no banco é metadado de laboratório, não ativação real.
Não existe approve/clear/activate nesta revisão.

Próximo bloco: A1.5, coordenador que consulta o registry ao iniciar e antes de
agendar candidatos, separa ausência de visibilidade de degradação persistente,
aplica limites de trabalho e não reavalia o mesmo leitor/evidência em loop.
Depois vem integração controlada de seleção/promoção/rollback no runtime; treino
de modelos permanece uma capacidade distinta. As falhas 36/56 continuam abertas.

SQLite usa BEGIN IMMEDIATE e synchronous=FULL. Persistência depende de filesystem
local, locking e flush corretos; não há alegação de imunidade a falha física.
Cadeia SHA-256 não é assinatura/autenticação e não protege de reescrita maliciosa
por alguém com acesso total ao banco e aos relatórios. A API import_review é
interna: o importador verificado é o ponto de entrada do CLI. Não usar em NFS ou
como serviço multi-tenant sem outro desenho de segurança/persistência.

Referências: https://www.sqlite.org/atomiccommit.html e
https://docs.python.org/3/library/sqlite3.html .

## Testes

Suíte do registry: reabertura, idempotência, bloqueios persistentes, nova identidade,
concorrência, revisão obsoleta, exceção após escrita antes do commit e saída abrupta
de processo dentro de transação; corrupção e esquema incompatível falham fechados.
Suíte de importação: histórico sintético HP4/HP5 com os avaliadores reais, sem
executar OCR; alteração de hashes, decisão, manifesto, PTS/consenso e binário são
rejeitadas. Registros de teste não representam acurácia do TFT.
Resultados executados e hashes dos arquivos estão no PR. A importação real dos
relatórios nativos completos permanece para execução no Ubuntu do usuário.
