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

`riot-ddragon/` contém referências visuais oficiais fixadas por versão Data
Dragon, locale, set e hash. Não contém geometria de tela nem vincula uma gravação
a um patch TFT. `releases/` mantém o catálogo sazonal normalizado do provedor
secundário e seu vínculo explícito com patch TFT.
