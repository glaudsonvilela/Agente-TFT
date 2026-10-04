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

O release ativo fica em `configs/catalog/active-knowledge-release-v1.json`. A
versão 18.3 inclui atributos de combate, traços e descrições de habilidades de 74 campeões
jogáveis; o manifesto guarda URL e SHA-256 do snapshot CommunityDragon 16.19
em português brasileiro. `configs/ui` guarda a geometria fixa. Atualizar o
patch cria outro release; nunca sobrescreve este nem altera o tabuleiro.

A fonte expõe valores numéricos de habilidade para apenas 2 dos 74 campeões;
as 74 descrições contêm marcadores não resolvidos. O simulador não deve
interpretar esses marcadores como números. Valores alterados nas notas do
patch precisam de um pacote de regras verificado em separado.

O snapshot do cliente e a nota oficial podem divergir em ajustes intermediários
18.3 B. Até conferir esses valores e validar o simulador, `strategy_ready` fica
`false`: atributos servem para identificação e estudos, não para calcular uma
dica de combate como se sua precisão estivesse comprovada.
