# HP2 — diagnóstico temporal automático em trechos curtos

Base: HP1 / PR #14, `ca74f1636a2dc090b7e942e9bd18519b60c918f1`.

## Por que esta entrega

A execução HP1 enviada pelo usuário terminou com 40 frames, 35 localizações únicas,
30 leituras aceitas, 5 `badge_not_found`, 5 `ocr_uncertain` e zero erros operacionais.
Isso é disponibilidade de leitura, não 30 acertos comprovados. No log, 1550000 ms
mostra 36 aceito, 1600000 ms mostra 56 aceito e 1700000 ms mostra 36 aceito.
A inspeção visual de desenvolvimento do JPEG em 1600000 ms mostra 36: existe um
falso aceite no lote, apesar da concordância das duas escalas. Esta inspeção não
constitui avaliação independente dos demais frames.

O último -7 foi rejeitado porque uma escala ficou abaixo de 0.70. Os cinco campos
sem marcador não têm causa comprovada apenas pelo log. Não se transforma tudo em
"HUD encoberto", nem se excluem falhas do denominador para reportar acurácia.

## Escopo

HP2 adiciona coleta de evidências densa e automática. **Não corrige o falso aceite
por regra especial e não altera uma linha do leitor Rust HP1**, do OCR v4, dos
limiares, de StateFusion, do GameState ou de OpportunityWeights. A versão anterior
continua disponível para comparação.

O planejador lê um relatório nativo HP1 e escolhe, até o limite de 10 janelas:

- um trecho com leitura aceita como controle, sem chamá-lo de verdade;
- aumentos observados de HP, sem presumir que todo aumento seja impossível;
- erros/conflitos, leituras incertas e indicação negativa;
- ausência de marcador depois que ele já foi detectado.

As sugestões/labels/expected não escolhem a resposta. O planejador não contém os
valores 36/56 nem os timestamps do Match001. Eventos próximos compartilham uma
janela, e exclusões por orçamento aparecem explicitamente no plano.

## Extração temporal

Cada janela cobre aproximadamente um segundo antes e depois do evento. FFmpeg faz
seek no vídeo local e seleciona frames da fonte separados por pelo menos 250 ms,
sem filtro `fps` ou duplicação para inventar confirmações. Os PNGs preservam os
pixels da decodificação sem adicionar a recompressão JPEG do lote inicial; não são
os mesmos arquivos do ensaio esparso. Mudanças de resultado podem incluir essa
mudança de origem/formato de imagem.

A correspondência imagem/tempo é validada com `showinfo`: PTS inteiro e time base
ficam no manifesto. O campo `timestamp_ms` arredonda para cima, nunca para antes do
PTS. São exigidos timestamps crescentes, contagem correspondente à dos arquivos,
pelo menos dois frames e orçamento inferior a 12 frames por janela. Codec/seek,
EOF e timeout são erros explícitos. Uma origem temporal não-zero/desconhecida é
recusada nesta versão, em vez de assumir equivalência com o relógio do HP1.

Timestamps diferentes não provam erros independentes: quadros reais estáticos
podem ter pixels idênticos. O relatório conta checksums repetidos. PTS duplicado
é erro, não amostra nova. `max_gap_ms` mostra os intervalos reais, inclusive vídeo
com frame rate variável. O relógio serve ao replay, não é medição de latência real.

Referência técnica primária: documentação FFmpeg, opções `-ss`, `-t`, `-copyts`,
`-start_at_zero` e `-fps_mode`, https://ffmpeg.org/ffmpeg.html .

## Execução e análise

Um processo nativo HP1 novo é iniciado por janela. Isso reinicia tracker e health
entre trechos independentes. O consenso original de dois frames / 750 ms fica
intacto; `stable_current` pode aparecer agora, mas continua sendo confirmação
temporal de uma hipótese visual, **não verdade nem identidade de conta**.

Uma leitura errada persistente ainda pode passar no consenso temporal. HP2 não
promove perfis e não coloca resultados no estado estratégico. O aumento de HP é
apenas um alerta de diagnóstico; nenhum 56 é substituído por 36, nenhum número é
limitado pelo HP anterior, e nenhum negativo vira +7 ou eliminação inferida.

Os trechos são selecionados retrospectivamente. Mesmo que cada leitura/tracker
use apenas o passado dentro do trecho, o experimento não mede detecção causal de
drift em uma partida inteira. A métrica permanece `targeted_temporal_diagnostics`,
`exact_accuracy=null`. Não comparar sua cobertura diretamente com 30/40 para
concluir melhora: a distribuição da amostra é diferente.

## Comando

```bash
bash scripts/probe_match001_player_hp_dense.sh
# Ou usar explicitamente um relatório anterior:
bash scripts/probe_match001_player_hp_dense.sh telemetry/data/match-001-player-hp1.XXXX/report.json
```

Sem argumento, escolhe o relatório HP1 mais recente. O runner cria uma pasta nova
`telemetry/data/match-001-player-hp2.XXXXXXXX`. Salva ambiente, hashes de código,
perfil, relatório de origem e binário; plano, manifestos, PNGs com hashes, comandos,
stderr, eventos por janela e resumo. O vídeo tem tamanho/mtime registrados e
checados durante a extração; **isso não é hash completo nem prova de identidade
com a gravação usada no primeiro lote**. Os caminhos defaults são os do Match001.

Timeout de extração: 90 segundos por janela; processo HP1: 180 segundos. Falhas
permanecem em stderr/exit-code e nunca são tratadas como conclusão bem-sucedida.
Nada é sobrescrito. Não se percorrem novamente os 32 minutos nem se exige Labeler.

## Validação e próximo passo

Há testes de seleção sem labels, limites, ordem, preservação de relatórios,
correspondência imagem/PTS e origem de tempo. O job HUD media exige FFmpeg/FFprobe
e executa a integração com o binário Rust HP1 em vídeo sintético sem marcador.
Esse teste exige ausência de leitura e nenhuma confirmação inventada, não mede
reconhecimento numérico real. O teste nativo é pulado localmente sem Rust e obrigatório
no job de mídia. Resultados medidos de CI devem ser registrados no PR.

Em seguida, avaliar os trechos reais para distinguir instabilidade de recorte,
erro persistente de glifo, ocultação e mudança de contexto. Só depois ligar a
avaliação de candidatos A1 e o registry. Esta entrega coleta os exemplos difíceis
sem trabalho manual do usuário; não é retreinamento nem adaptação já ativada.
