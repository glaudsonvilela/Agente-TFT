# HP4 — avaliador automático da evidência pareada HP3

Base: HP3, commit `f76c0ab76f2e5ca6c386096d6ef61b35b99faf82`.
É uma revisão offline dos relatórios existentes, não outro perfil OCR.

## Resultado recebido e decisão de desenvolvimento

No grupo denso de 80 PNGs, a candidata apresentou 41 HPs não negativos aceitos
contra 31 do HP1; 8 negativos contra 3; 31 confirmações temporais contra 22.
Há 16 leituras exclusivas da candidata, uma exclusiva do baseline e 33 pares
legíveis iguais. Nos 40 JPEGs: 31 HPs não negativos aceitos contra 30, um negativo
contra zero, quatro leituras exclusivas da candidata e duas do baseline.
Não há pares finais legíveis divergentes nesses resumos.

Isso é ganho de disponibilidade, não acurácia. As três leituras exclusivas do
baseline não são necessariamente erros da candidata: o baseline tem um caso
conhecido de leitura incorreta. O resumo não localiza essas perdas e não permite
concluir o que a candidata fez no JPEG de 1600000 ms. Não substituir o baseline
por causa do saldo positivo das contagens.

## O que HP4 executa

Lê `plan.json`, `report.json`, manifests e relatórios individuais do HP3. Recalcula
contagens e comparações a partir dos registros. Valida timestamps, identificadores,
valores assinados, confiança, duas escalas elegíveis, classificação e localização
igual entre leitores. Reproduz o contrato temporal HP1 (750/1500 ms) para verificar
confirmações, gaps, último valor bom e idade. Não preenche nenhum valor ausente.

Também encontra tentativas elegíveis contrárias: um leitor pode ter status final
unknown por uma escala fraca, mas sua outra escala elegível discordar do valor
aceito pelo outro leitor. O HP3 só imprime divergências entre DUAS leituras finais
aceitas; HP4 torna esse caso parcial explícito. Nenhuma tentativa vira rótulo e
não se resolve divergência pela maior confiança.

Os casos de apenas um leitor legível, ambos divergentes ou ambos sem leitura
ficam em `cases.jsonl`, com timestamp, lote, hash registrado da imagem, traces,
perfil e enquadramento. `target_hp=null` e `eligible_for_training=false` impedem
que essa fila seja anunciada como dataset supervisionado. Os identificadores de
caso e de auditoria são determinísticos para a mesma evidência/política.

## Política de revisão v1

| Evidência | Ação de revisão |
|---|---|
| Valores aceitos divergentes ou tentativa elegível contrária, incluindo sinal | `quarantine_candidate` |
| Leituras exclusivas do baseline ainda sem explicação | `hold_candidate` |
| Ganho exclusivo sem riscos acima | `ready_for_disjoint_shadow` |
| Sem ganho operacional | `keep_baseline_no_operational_gain` |

Todas as ações mantêm `active_action=retain_baseline` e `profile_promoted=false`.
Pronto para outra avaliação não significa promovido. Os lotes HP3 foram escolhidos
retrospectivamente para diagnóstico; não fornecem validação fora da seleção.
Não é necessária rotulagem humana para executar essa revisão ou continuar o
desenvolvimento. A regra de revisão não exige concluir que toda perda é erro.

## Segurança, arquivos e integração

No máximo 11 lotes/160 frames, 16 MiB por JSON e 64 MiB de leitura total, inclusive
checagem final. Rejeita JSON duplicado/não finito, alterações de manifests,
contagens inconsistentes, duplicação temporal, troca da localização e caminhos
que escapem por symlink. Só aceita o par de perfis HP3 conhecido; uma mudança de
contrato requer uma nova versão de auditoria.

Cria uma pasta nova APÓS a validação. Não sobrescreve os relatórios de origem;
`COMPLETE` sinaliza término. Se houver erro antes do término, não usar arquivos
parciais. Os hashes de relatórios representam o conteúdo lido na auditoria, não
uma assinatura retroativa da execução. Os hashes de imagens/perfil/binário são
referências copiadas do plano HP3: HP4 não abre nem revalida esses arquivos.

Não chama Cargo, FFmpeg, Tesseract, rede ou segundo modelo; não decodifica imagens.
A política operacional A1.3 não é invocada nem recebe snapshots fabricados.
O resultado é um registro de avaliação utilizável na futura integração, não um
registry ativo, treinamento ou ciclo completo de adaptação. Não escreve GameState,
OpportunityWeights, OCR, ROIs, perfis ativos ou anotações.

## Execução

```bash
bash scripts/audit_match001_player_hp_candidate.sh \
  telemetry/data/match-001-player-hp3.oHRX0Yzj
```

Saída nova `telemetry/data/match-001-player-hp4.XXXXXXXX/audit/`.
O console imprime `HP4_CASE` para perdas/contradições e `HP4_SUMMARY` com a decisão.
Não há timestamps de resposta, HP esperado ou correção 56→36 embutidos no código.

## Validação

A suíte usa registros sintéticos de contrato, incluindo perdas, ganhos,
contradições parciais, sinal negativo, aceitação falsa de uma escala, tampering,
duplicação, separação denso/esparso, serialização e não sobrescrita.
Ela não executa o novo avaliador nos relatórios completos do usuário: esses
relatórios permanecem no Ubuntu. O log de console recebido só contém agregados.
Os resultados dos testes locais e CI devem ser registrados no PR.

## Próxima etapa

Usar os casos completos para escolher uma política candidata congelada e testá-la
em sequência diferente da usada para seleção, antes de conectar ativação e
rollback persistentes. Não lançar sucessivos ajustes OCR apenas para fechar
100% do Match001; leituras novas, perdas e ambiguidades precisam continuar
visíveis ao avaliador automático.
