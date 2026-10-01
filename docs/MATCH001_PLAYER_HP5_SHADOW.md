# HP5 — comparação congelada em sequências temporalmente distintas

Base: HP4, `921a5d496278ab75e5714680e86d2f3c07ec90bf`.

## Resultado recebido e decisão preservada

A auditoria nativa reportada pelo usuário retornou `quarantine_candidate` e
`retain_baseline`. Em 1649750 e 1550000 ms, HP1 aceitou 36 nas duas escalas;
a candidata produziu 36/56 e corretamente se absteve por conflito. Em 1600000 ms,
HP1 aceitou 56; a candidata rejeitou 36 com confiança 0.692 e 356 fora do domínio.
A terceira perda de disponibilidade NÃO deve ser classificada como perda de um
acerto. Estes resultados não resolvem o caso conhecido 36/56 do JPEG e não
transformam o baseline em ground truth.

HP3 já mostrou ganho de disponibilidade: 16 leituras exclusivas da candidata no
grupo denso e 4 no esparso, contra 1 e 2 exclusivas do baseline. Isso não basta
para ativar o perfil. HP5 preserva os bloqueios históricos, inclusive quando uma
sequência nova parece mais fácil.

## Entrega

Um comando executa seleção, extração, comparação nativa e auditoria dos pares.
Não há novo OCR, nova ROI manual, busca de thresholds ou anotação humana.

1. Verifica HP4/COMPLETE, audit_id e SHA-256 de todos os relatórios/manifests
   auditados. Recalcula a decisão HP4 com os registros originais; não confia em
   um campo `quarantine` editável isoladamente.
2. Exige os MESMOS bytes do executável Rust HP3 e do perfil do marcador
   registrados pelo HP3. Não recompila automaticamente. Se o binário mudou,
   interrompe; não remove a verificação para produzir um resultado.
3. Usa somente timestamps/intervalos registrados no plano HP3 para excluir a
   amostragem anterior. Um trecho denso é excluído inteiro, do primeiro ao último
   frame, mais margem de 5 segundos; cada timestamp esparso recebe a mesma margem.
4. Divide a duração em três partes. Em cada parte escolhe o centro do maior
   intervalo livre (empate: primeiro intervalo). Extrai **8 segundos por parte**.
   A escolha depende de tempo/espaço disponível, NÃO de HP, confidence ou status.
5. Salva plano e hash ANTES de decodificar e ler. Se um trecho falhar, não troca
   por outro mais favorável. Falta de espaço disjunto é erro explícito.
6. Reutiliza o extrator HP2, sem modificar seus limites: quatro blocos adjacentes
   de 2 segundos formam cada sequência de 8 segundos. Verifica novamente PTS,
   bordas e intervalo entre frames inclusive nas junções. Não usa filtro fps
   para duplicar quadros. Exige 24..47 frames por sequência, no máximo 144 total,
   gaps entre 250 e 500 ms, e cobertura das duas bordas com tolerância de 500 ms.
7. Executa o binário pareado HP3 uma vez por sequência, sobre o mesmo frame para
   os dois leitores. Os trackers são preservados entre os quatro blocos da
   sequência e reiniciados entre sequências. Timeout mata o grupo de processos.
8. Reutiliza `review_batch` do HP4 para escalas, sinais, contradições e
   confirmações temporais. Não fabrica snapshots A1 a partir de estatísticas.
9. Revalida fontes, perfil, executável e plano, além do SHA-256 atual do vídeo,
   antes de registrar conclusão. Cada caso continua sem target de treino.

## Identidade e limites

A disjunção é em relação aos intervalos declarados no HP3, da MESMA gravação.
Não é teste de outra partida, nem independência estatística, nem garantia de
acurácia. As imagens históricas não são reabertas; seus manifests/report hashes
são verificados. O vídeo histórico HP2 tinha somente tamanho/mtime; HP5 exige
compatibilidade com esses metadados e registra SHA-256 atual, mas isso não
comprova retrospectivamente a identidade dos bytes usados no HP2.

O freeze cobre executável Rust e perfil. As versões FFmpeg/Tesseract são
registradas; não se afirma que todas as bibliotecas dinâmicas ou arquivos de
idioma sejam idênticos ao ambiente anterior. Ambos os leitores rodam no mesmo
ambiente atual. Timestamps diferentes podem mostrar pixels iguais; checksums
repetidos ficam explícitos, não viram prova de exemplos independentes.

O HP5 NÃO libera uma candidata antes colocada em quarentena. Mesmo que os novos
resultados melhorem, `candidate_activation_blocked=true` continua. Não grava
active.json, não altera GameState, OpportunityWeights, OCR ou regras, não treina
modelo e não chama o resultado de autoaprendizado concluído.

O objetivo desta etapa é parar de escolher correções com base somente nos três
casos conhecidos. O próximo critério é integrar uma candidata que resolva seus
bloqueios de maneira geral e passe regressão + avaliação separada; não mais
prescrever correções 56→36 ou ajustar o último timestamp até obter 100%.

## Execução

```bash
bash scripts/probe_match001_player_hp_disjoint.sh \
  telemetry/data/match-001-player-hp4.mcuRgxvk
```

Usa o binário release já produzido no HP3. Não requer Cargo nesta execução.
Aceita também o caminho `audit/report.json` diretamente. Saída exclusiva:

```
telemetry/data/match-001-player-hp5.XXXXXXXX/
  environment.txt
  run.stdout / run.stderr
  run/plan.json
  run/sequence-00/ ... sequence-02/
  run/cases.jsonl
  run/report.json
  run/COMPLETE.json
```

Imprime HP5_PLAN, HP5_WINDOW, HP5_SUMMARY e HP5_REPORT. A ausência de COMPLETE.json
indica execução não concluída. Hashing do vídeo acrescenta leitura de disco, mas
somente 24 segundos de imagens são selecionados para esta avaliação (há também
a decodificação necessária ao seek de cada bloco).

## Testes

Testes de planejamento/disjunção, congelamento de identidade, quarentena
persistente, timestamps, truncamento, checksum repetido, integridade e não
sobrescrita. A integração nativa obrigatória no HUD media cria vídeo sintético,
produz o histórico HP3/HP4 com o executável real e percorre a nova avaliação.
Sem marcador no vídeo sintético, não pode inventar HP. Isso valida contratos e
fluxo; não mede a acurácia do Match001. Resultados executados são registrados no PR.

Referências de timestamp: documentação oficial FFmpeg `trim`, `showinfo`,
`-copyts` e `-fps_mode passthrough`. Os comandos permanecem no extrator HP2.
