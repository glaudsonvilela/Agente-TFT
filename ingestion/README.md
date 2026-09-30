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

## Normalizar CommunityDragon

O arquivo bruto do CommunityDragon é grande. Depois do sync, gere um pacote estático compacto selecionando explicitamente o set:

```bash
python -m ingestion.normalize_cdragon \
  --input knowledge/raw/communitydragon_tft_pt_br.json \
  --set TFTSet17 \
  --output knowledge/database/tft_static.json
```

O normalizador aceita `setData` em formato array ou objeto e produz apenas:

- campeões;
- traits;
- itens;
- augments;
- metadados do set;
- SHA-256 da fonte.

A seleção do set deve ser explícita para evitar misturar conteúdo evergreen, PvE ou sets antigos.

## Catálogo de campeões por set

Depois de sincronizar o JSON TFT do CommunityDragon:

```bash
python -m ingestion.build_unit_catalog knowledge/raw/communitydragon_tft_pt_br.json --list-sets

python -m ingestion.build_unit_catalog \
  knowledge/raw/communitydragon_tft_pt_br.json \
  --set <SET_EXPLICITO> \
  --output knowledge/unit_catalog.json
```

O comando não escolhe o set silenciosamente. O set precisa ser explícito para evitar misturar revival/PBE/sets antigos.

## Assets de unidades

```bash
python -m ingestion.download_unit_assets \
  knowledge/unit_catalog.json \
  --output-dir knowledge/assets/units
```

O downloader prioriza `squareIcon`, grava arquivos atomicamente e registra SHA-256 em `manifest.json`. Os binários baixados ficam fora do Git.
