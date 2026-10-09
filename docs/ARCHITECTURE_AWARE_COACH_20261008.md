# Coach TFT com consciência situacional — pesquisa e arquitetura

## O que queremos dizer por “consciente”

Queremos um agente que mantenha uma hipótese atualizada da partida, reconheça
incerteza, escolha metas, antecipe alternativas, acompanhe o resultado das
próprias recomendações e explique suas escolhas. Isso é uma definição funcional
e verificável; não afirma experiência subjetiva. O estudo de Dehaene, Lau e
Kouider separa a difusão global de informações para decisão (C1) da
autoavaliação de certeza/erro (C2). A revisão de Butlin et al. propõe
indicadores arquiteturais, mas não um teste conclusivo de consciência.

## Diagnóstico do projeto em 8 de outubro de 2026

- `match_memory.rs` já registra observações e mantém uma pool por partida.
- `match_brain.rs` combina evidências recentes, mas só cria oportunidades
  nativas de par na loja e ativação condicional de traço.
- `live_rank.rs` compara candidatos por utilidade, pressão de vida e repetição.
- A camada Python ainda cria alguns candidatos e prepara frases. A identidade
  visual de unidades, itens e o vínculo com o adversário frequentemente ficam
  como candidatos, não fatos confirmados.

Isso é um início de **memória e arbitragem**. Ainda não há um modelo de mundo
treinado que preveja transições, um plano persistente com revisões ou um ciclo
medido de previsão → resultado → correção. A fala convincente não deve ser
usada como prova de boa decisão.

## Arquitetura proposta

```text
captura Rust → percepções com origem/tempo/confiança → crença da partida
                                                  ↕
                                   memória episódica e de adversários
                                                  ↓
                             espaço de trabalho: ameaça, meta, oportunidades
                                                  ↓
                       Rust: ações viáveis → cenários → utilidade/risco
                                                  ↓
                        plano atual + escolha + evidências + incerteza
                                                  ↓
                         linguagem: explicação fiel → texto/voz
                                                  ↓
                         resultado observado → crítico → aprendizado
```

### 1. Crença em vez de leitura isolada

Cada entidade guarda identidade provável, posição, instante e origem. Uma
observação nova atualiza a crença; um dado ausente não apaga um fato anterior,
mas sua confiança decai. Mudança de fase, replay seek e troca de adversário
isolam o contexto relevante. A observação incerta permanece hipótese: não vira
rótulo de treino nem autoriza uma afirmação categórica.

### 2. Metas e atenção

O agente acompanha metas de horizonte curto (sobreviver à próxima luta,
aproveitar uma loja), médio (estabilizar composição/itens) e longo (economia,
transição). Um espaço de trabalho escolhe o problema mais importante agora,
comparando custo de silêncio, urgência, novidade e efeito esperado. Essa é uma
aplicação de engenharia inspirada pelo C1; não é evidência de consciência.

### 3. Planejar antes de falar

O Rust gera ações de todas as famílias relevantes: comprar, rolar, subir nível,
guardar, equipar, reposicionar e observar um adversário. Para cada ação,
calcula legalidade, custo, cenários possíveis e valor esperado sob as crenças
atuais. O plano persiste por várias rodadas e muda quando surge evidência melhor.
Um modelo de mundo aprendido pode estimar transições; regras exatas do patch
continuam em dados sazonais separados. Nunca extrapolar para uma partida real
a qualidade de um simulador ainda incompleto.

### 4. Autoavaliação e aprendizagem

Antes da dica, registrar previsão e confiança: “esta compra deve ativar o
traço”, “esta troca deve reduzir dano recebido”. Depois, comparar previsão e
resultado. O crítico identifica erro de percepção, erro de modelo, execução do
jogador ou variância da luta. Aprende no BigBANANA a partir de episódios
verificados e versões de patch; no Windows, aplica um modelo versionado leve.
O usuário continua recebendo texto imediatamente, sem esperar a voz remota.

### 5. Linguagem ligada ao plano

A geração de fala recebe somente a escolha, as evidências, o histórico breve
e os limites de certeza. Pode variar a expressão e ter personalidade, mas não
inventar ações, causas de derrota ou identidades de campeões. Se não houve
causa identificada, deve admitir isso em vez de produzir uma frase clichê.
Essa separação segue o princípio observado no CICERO: linguagem coordenada a
planejamento estratégico, não linguagem usada como substituto do plano.

## O que aproveitar da pesquisa

| Trabalho | Ideia aproveitável | Limite para TFT |
| --- | --- | --- |
| Dehaene et al., 2017 | Espaço de trabalho global e autoavaliação de erro | Teoria não prova consciência da implementação |
| Butlin et al., 2025 | Indicadores arquiteturais para avaliar alegações | Indicadores não são um certificado de experiência subjetiva |
| Generative Agents, 2023 | Observação, memória, reflexão e plano persistente | Comportamento crível não garante estratégia correta |
| CICERO, 2022 | Fala condicionada a planos e modelo dos outros jogadores | Diplomacy tem estado e ações diferentes de TFT |
| DreamerV3, 2025 | Aprender transições e comparar futuros imaginados | Exige dados e avaliação; não copiar o modelo inteiro para um PC mediano |
| Voyager, 2023 | Biblioteca de habilidades e currículo de aprendizado | Um agente exploratório pode ser lento e inadequado em partida ao vivo |
| AlphaStar, 2019 | Treino offline em massa e política compacta em jogo | Custos de treinamento e observação são muito diferentes |

## Ordem de implementação e critérios de saída

1. **Crença da partida:** leituras de fontes diferentes coexistem com tempo e
   confiança; replay seek e partida nova não misturam memória. Testar com
   sequências em que dados somem e reaparecem.
2. **Plano persistente:** o sistema registra meta, alternativas descartadas e
   motivo da mudança. A mesma loja em contextos diferentes deve produzir
   decisões diferentes, com explicação baseada no contexto.
3. **Previsão e crítico:** cada dica guarda previsão verificável e resultado;
   o crítico separa erro de leitura de erro estratégico. Nenhuma previsão
   automática passa a ser rótulo verdadeiro sem reconciliação.
4. **Coach completo na interface:** medir variedade útil, relevância, latência
   entre evento e texto, fala, repetição e qualidade da justificativa ao longo
   de partidas completas. Texto não depende da latência da API de voz.
5. **Generalização:** separar partidas inteiras entre desenvolvimento e
   avaliação, incluindo versões/transcodificações do mesmo VOD no mesmo grupo.
   Um trecho observado para depuração vira desenvolvimento; a validação final
   usa outro jogo ainda não visto. Registrar identificador de fonte, partida,
   intervalos e patch, sem publicar mídia privada.

## Fontes primárias

- Dehaene, Lau e Kouider, *What is consciousness, and could machines have it?* (Science, 2017): https://pubmed.ncbi.nlm.nih.gov/29074769/
- Butlin et al., *Identifying indicators of consciousness in AI systems* (Trends in Cognitive Sciences, 2025): https://www.sciencedirect.com/science/article/pii/S1364661325002864
- Park et al., *Generative Agents* (UIST, 2023): https://arxiv.org/abs/2304.03442 ; código: https://github.com/joonspk-research/generative_agents
- Meta FAIR, *Human-level play in Diplomacy* (Science, 2022): https://pubmed.ncbi.nlm.nih.gov/36413172/ ; código: https://github.com/facebookresearch/diplomacy_cicero
- Hafner et al., *Mastering diverse control tasks through world models* (Nature, 2025): https://www.nature.com/articles/s41586-025-08744-2 ; código: https://github.com/danijar/dreamerv3
- Wang et al., *Voyager* (2023): https://arxiv.org/abs/2305.16291 ; código: https://github.com/MineDojo/Voyager
- Vinyals et al., *Grandmaster level in StarCraft II* (Nature, 2019): https://www.nature.com/articles/s41586-019-1724-z
