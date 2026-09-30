# ingestion/

Pipeline que sincroniza fontes externas fora do caminho crítico da partida e constrói um **Knowledge Pack local, normalizado e versionado por patch**.

## Fontes iniciais

- Riot Data Dragon versions;
- CommunityDragon TFT pt-BR.

A lista fica em `sources.json`.

## Sincronizar

```bash
python -m ingestion.sync_sources --list
python -m ingestion.sync_sources --source riot_ddragon_versions
python -m ingestion.sync_sources --source communitydragon_tft_pt_br
python -m ingestion.sync_sources --source all
```

Use `--force` para ignorar TTL.

## Saída

Arquivos em:

```text
knowledge/raw/
├── riot_ddragon_versions.json
├── communitydragon_tft_pt_br.json
└── manifest.json
```

O manifest registra:

- URL;
- timestamp;
- TTL;
- SHA-256;
- tamanho;
- ETag;
- Last-Modified;
- content type.

Os arquivos são gravados atomicamente.

## Princípio

```text
internet
   ↓
sync offline/background
   ↓
validate
   ↓
hash
   ↓
knowledge/raw
   ↓
normalize/index
   ↓
Knowledge Pack
   ↓
partida consulta LOCAL
```

O agente não deve baixar arquivos pesados no meio de uma decisão.
