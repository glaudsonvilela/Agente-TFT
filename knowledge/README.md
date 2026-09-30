# knowledge/

Conhecimento local do TFT.

Separar:

- dados estruturados → SQLite/tabelas;
- regras/mecânicas → código ou registros tipados;
- texto contextual → busca textual/embeddings quando útil.

Campos mínimos:

```text
source
patch
set
type
id
collected_at
expires_at
confidence
source_hash
```

Patch anterior deve ser marcado como `STALE`.
