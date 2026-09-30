# ingestion/

Pipeline para transformar fontes externas em um **Knowledge Pack local, normalizado e versionado por patch**.

Fontes possíveis:

- Riot APIs;
- Data Dragon;
- CommunityDragon;
- fontes externas permitidas/importadas;
- datasets próprios.

Pipeline:

```text
source → fetch → validate → normalize → dedupe → patch-tag → persist → index
```

Nenhum conteúdo externo deve entrar diretamente no agente sem provenance e versão.
