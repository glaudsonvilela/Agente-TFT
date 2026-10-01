# A1.2 — ROI/Anchor Candidate Search em Shadow

Base: A1.1 `perception-health`.

## Objetivo

Quando um stream de percepção estiver degradado, A1.2 fornece a busca limitada
de posições alternativas. A busca não altera o perfil ativo. Ela produz somente
um candidato para avaliação em shadow.

## Entradas

```text
RoiSearchSeed
├── active_read_rect
├── active_anchor_rect
├── resolução
├── subsystem / field
├── active_profile_id
└── search_id
```

A área de leitura e a âncora se movem juntas pelo mesmo deslocamento. Isso evita
selecionar um número aleatório em outra região apenas porque o OCR conseguiu
interpretá-lo.

A âncora usa o `visual-match` já existente. Similaridade visual é score bruto,
não confidence calibrada.

## Busca

A busca gera somente translações da geometria existente:

```text
dx ∈ [-max_x, +max_x]
dy ∈ [-max_y, +max_y]
step configurável
```

Restrições:

- caixas devem continuar totalmente dentro do frame;
- número máximo de candidatos é limitado;
- `active` (0,0) é sempre preservado quando válido;
- candidatos próximos são gerados primeiro;
- nenhuma dimensão da ROI é ampliada automaticamente nesta etapa.

A1.2 não aprende escala/rotação. Esses graus de liberdade só devem entrar depois
de evidência de necessidade.

## Avaliação sem labels

Cada candidato é executado nos mesmos frames e recebe duas famílias de sinais:

1. **read health**
   - accepted;
   - unknown;
   - conflict;
   - error;
   - coverage;
   - confidence p50/p95.

2. **anchor**
   - similaridade visual p50/p95;
   - erros de âncora.

Não existe parâmetro `expected` ou ground truth na API de busca.

O stream de health de cada candidato é isolado:

```text
active_profile::shadow::search_id::candidate_id
```

Assim a janela do perfil ativo nunca se mistura com a do candidato.

## Elegibilidade

Um candidato precisa passar simultaneamente:

- mínimo de frames;
- coverage mínima;
- confidence p50 mínima;
- similaridade de âncora p50 mínima;
- zero erros de âncora no lote.

Depois disso recebe um `operational_score`, combinação explícita e configurável
de coverage, confidence e âncora. O score é somente ranking operacional, nunca
probabilidade ou accuracy.

## Ambiguidade

Se o melhor candidato não superar o segundo elegível pela margem mínima, o
resultado é abstention:

```text
shadow_candidate_id = null
```

Se o perfil ativo continuar sendo o melhor, também não existe candidato shadow.

## Regra principal

Mesmo quando existe `shadow_candidate_id`, A1.2 NÃO:

- escreve layout;
- altera active profile;
- muda GameState;
- muda OpportunityWeights;
- muda OCR thresholds;
- promove candidato.

A promoção/rejeição persistente pertence ao A1.3.

## Teste sintético obrigatório

O crate contém um cenário conhecido:

1. frame de referência com uma âncora em x=10 e campo em x=20;
2. frames de avaliação movem ambos +20 px;
3. a busca recebe somente pixels e outcomes do probe;
4. deve retornar `dx+20_dy+0` como candidato shadow;
5. duas posições igualmente boas devem produzir abstention;
6. se active continuar melhor, não deve criar candidato.

O teste é de contrato e geometria, não prova de generalização em TFT real.

## Próximo bloco

A1.3:

```text
active + candidate
       ↓
execução shadow contínua
       ↓
janela comparável
       ↓
promotion gate
       ├── promote
       ├── reject
       └── rollback
```

A1.3 deve registrar toda decisão de promoção e nunca usar redução de unknown
isoladamente como critério suficiente.
