# HP1 — leitura dinâmica do marcador ampliado na player_list

Base: A1.3, commit 958a5780b84542e0b54511154325a16ae32cae01. Entrega opt-in de laboratório/replay. Não altera o HUD v4, os crates existentes, GameState, OpportunityWeights ou perfis ativos.

## Inspeção e hipótese visual

Os 40 JPEGs do AI batch foram inspecionados para desenvolver um localizador. O marcador ampliado possui uma borda em chevron que muda de posição na lista. O prefixo da borda não contém nome, avatar ou dígitos; os pontos estruturais foram semeados de `0030_001450000ms.jpg`, (1771,420,26,49). A região de busca inclui a lista inteira, não uma linha fixa. O recorte de HP é relativo ao marcador encontrado.

O nome self-badge descreve uma hipótese visual desta gravação, NÃO uma identidade de conta comprovada e NÃO um detector universal para qualquer set, patch ou modo espectador. Mudanças na forma/cor/escala ou nos indicadores de seleção podem exigir outro perfil. Não se usa o nickname/avatar do jogador como template e não se escolhe linha pelo HP esperado.

Na inspeção, painéis de unidade encobrem a lista em 750000 e 800000 ms. O frame final exibe -7; descartar o sinal produziria a leitura falsa +7. São observações visuais de desenvolvimento, não rótulos humanos de avaliação independente.

## Localização

`perception-player-list` constrói máscaras de cor dourada e interior escuro, usa tolerância espacial de um pixel e busca o prefixo estrutural dentro da região configurada. Os limites de pixels, pontos, candidatos e resolução são validados antes da busca. O número de linha não é fixado. A semente estrutural continua versionada: HP1 não treina pesos nem aprende sozinho uma forma nova.

Zero marcadores: `badge_not_found`. Mais de um marcador após supressão local: `badge_ambiguous`. Orçamento excedido: `search_budget_exceeded`. Em todos esses casos não se chama OCR nem se lê a linha do adversário por proximidade. O score visual não é probabilidade/confiança calibrada de identidade.

## OCR assinado, sem novo backend

Reutiliza `TesseractOcr::with_numeric_gray()`. O adaptador usa a preparação Gold existente (projeção acromática que atenua a borda dourada) e a seleção Stage do backend exclusivamente para PSM7 e whitelist `0123456789-`. Não chama parser de estágio nem de gold. A observação, o parser e o relatório permanecem HP. Esse detalhe explícito evita modificar o backend e seus perfis v2/v3/v4.

Escalas 3x e 4x precisam concordar, ambas com confiança >=0.70. O parser aceita apenas inteiro assinado, dentro de -300..300. Negativos ficam em `signed_hp`/`negative_display` e NÃO são convertidos em HP unsigned, zero ou estado de eliminação inferido. Um -7 versus +7 elegível é conflito. Texto rejeitado permanece no trace; não recebe nova chance por coincidir com um prelabel.

Duas escalas do mesmo frame não são duas observações temporais independentes. Os escores de confiança não equivalem a probabilidade calibrada.

## Tempo e estado

`HpTracker` exige dois frames distintos, timestamps estritamente crescentes e intervalo de até 750 ms. Replicações do frame e lacunas de 50 s não produzem consenso. Missing/negativo quebra a sequência; último valor bom e idade ficam separados do valor atual. Leituras confirmadas refrescam o timestamp. O tracker deve ser recriado por sessão/fonte.

O probe reutiliza todos os caminhos/timestamps do manifesto `prelabels.json`, IGNORANDO sugestões/labels. Os JPEGs esparsos não fornecem a confirmação temporal densa: `stable_current=null` é esperado, não falha. O relatório mede disponibilidade operacional, mantém `exact_accuracy=null` e não escreve GameState.

## Relação com A1

HP1 exporta snapshots de Perception Health separados para `player_list/hp`. A1.2 e A1.3 continuam disponíveis, mas não estão conectados automaticamente a esse leitor: HP1 não promove, grava, aprende nem ativa um novo perfil. Health conta todos os frames fornecidos, inclusive pré-HUD/encobertos; não dispara drift/recalibração a partir dessa amostragem esparsa. Ainda falta ligar o ciclo completo health → busca → avaliação temporal → registry atômico. A fundação A1 não deve ser descrita como autoaprendizado completo.

## Execução

```bash
bash scripts/probe_match001_player_hp.sh
```

Pasta exclusiva `telemetry/data/match-001-player-hp1.XXXXXXXX`, com report.json, events.jsonl, environment.txt e stderr. Sem rotulagem manual, segunda IA, leitura de memória, acesso ao processo do jogo ou mudanças nos relatórios anteriores.

A implementação será compilada/testada no CI. O ambiente de edição possui os JPEGs, Python, FFmpeg e Tesseract 5.5.0, mas não Rust; uma tentativa de clone local falhou por DNS. Ensaios Python da geometria não são uma execução deste binário Rust, nem acurácia. A medição completa do binário no Ubuntu 5.3.4 é o passo seguinte; resultados CI e medições posteriores devem constar do PR.

## Próximos passos

Medir este probe no mesmo lote; depois ligar a sequência densa/identidade contextual ao loop adaptativo e ao estado, preservando ausência e idade. HP de todos os adversários e identidade por nome não são implementados nesta entrega. Não adicionar loja/tabuleiro antes de distinguir leitura isolada, consenso temporal e perfil ativo.
