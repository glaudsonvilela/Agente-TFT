# MetaTFT source adapter

MetaTFT is used as an **optional external meta prior**.

Public pages of interest include:

- https://www.metatft.com/comps
- https://www.metatft.com/units
- https://www.metatft.com/items
- https://www.metatft.com/traits
- https://www.metatft.com/augments
- https://www.metatft.com/explorer
- https://www.metatft.com/leaderboard

## Rules for this adapter

- no private/internal endpoint reverse engineering;
- no credentials or premium-content bypass;
- no high-frequency request loop during a match;
- snapshot is collected outside the critical path;
- provenance/source URL is mandatory;
- patch/set/rank/window are recorded;
- stale or mismatched data is ignored by Rust;
- MetaTFT data is not republished wholesale by this project.

The public site currently exposes live statistical views, while some pages (including `/comps`) require JavaScript. Therefore the initial adapter imports a public/exported browser snapshot rather than depending on undocumented internal APIs.

## Input format

```json
{
  "source_url": "https://www.metatft.com/comps",
  "captured_at_ms": 1234567890,
  "patch": "18.3b",
  "set": "TFTSet18",
  "queue": "ranked",
  "rank_filter": "platinum_plus",
  "window": "last_3_days",
  "entities": [
    {
      "kind": "comp",
      "id": "example-comp",
      "name": "Example Comp",
      "unit_ids": ["TFT18_A"],
      "trait_ids": ["TFT18_TRAIT"],
      "performance": {
        "avg_place": 4.1,
        "top4_rate": 0.54,
        "win_rate": 0.14,
        "frequency": 0.05,
        "sample_size": 12000
      },
      "tags": []
    }
  ]
}
```

Normalize:

```bash
python -m ingestion.import_metatft_snapshot snapshot.json \
  --output knowledge/meta/metatft.json
```

The resulting JSON maps directly to the Rust `MetaSnapshot` contract.
