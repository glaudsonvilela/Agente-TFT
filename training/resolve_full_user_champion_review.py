#!/usr/bin/env python3
"""Map one numbered human review to fixed crop IDs, keeping uncertain cases out."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata


ALIASES = {
    "azuporaop": "Azuporã", "azerpau~a": "Azuporã", "azerpauao": "Azuporã",
    "lilian": "Lillia", "lillian": "Lillia",
    "erzeal": "Ezreal", "erzeral": "Ezreal",
    "le blanck": "LeBlanc", "le black": "LeBlanc", "leblanck": "LeBlanc",
    "fidllstick": "Fiddlesticks", "orn": "Ornn",
    "kogmown": "Kog'Maw", "kog mow": "Kog'Maw", "kowg mwon": "Kog'Maw",
    "kowgmwon": "Kog'Maw", "kpg mow": "Kog'Maw",
    "nidalle": "Nidalee", "nidalcle": "Nidalee",
    "yorike": "Yorick", "yorick": "Yorick",
}
EXCLUDE_QUALITY = {"nao presta", "cortada", "cortado", "cprtada", "sem visao", "sem visaaop"}
EXCLUDE_NON_CHAMPION = {"passiva", "pasisva", "isso ai e um personagel do jogadro", "apenas logo de heroi"}
UNRESOLVED_OBJECT = {"sem identificacao", "a pedra azucl a", "pedra azul", "azul", "lobo"}
MIXED = {"shen com outro campeao": "Shen", "gnar + um capemao": "Gnar"}
PARTIAL_NAMED = {"grompe(meio cortado)": "Grompe"}
CONFLICT_WITH_PRIOR = {"E-069", "E-076"}


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip(" ;.")


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-tsv", type=Path, required=True)
    parser.add_argument("--frozen-audit", type=Path, required=True)
    parser.add_argument("--shop", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    lines = [line.split("\t", 1) for line in args.review_tsv.read_text(encoding="utf-8").splitlines()]
    audit = json.loads(args.frozen_audit.read_text(encoding="utf-8"))
    source_rows = audit["remaining"]
    if len(lines) != 116 or len(source_rows) != 116:
        raise ValueError("The numbered review must match the frozen 116-crop order")
    shop = json.loads(args.shop.read_text(encoding="utf-8"))
    names = {clean(row["name_pt_br"]): row["name_pt_br"] for row in shop["rows"]}
    entries = []
    decisions = {}
    for index, ((number, raw), source) in enumerate(zip(lines, source_rows), 1):
        if int(number) != index:
            raise ValueError(f"Review sequence mismatch at {index}: {number}")
        ident = source["id"]
        normalized = clean(raw)
        champion = None
        if normalized in EXCLUDE_QUALITY:
            status = "unusable_crop"
        elif normalized in EXCLUDE_NON_CHAMPION:
            status = "not_champion_body"
        elif normalized in UNRESOLVED_OBJECT:
            status = "identity_unresolved"
        elif normalized in MIXED:
            status, champion = "multi_unit_crop", MIXED[normalized]
        elif normalized in PARTIAL_NAMED:
            status, champion = "partial_body", PARTIAL_NAMED[normalized]
        else:
            champion = ALIASES.get(normalized, names.get(normalized))
            if champion is None:
                raise ValueError(f"Unmapped human label {index} {ident}: {raw}")
            status = "identity_conflict" if ident in CONFLICT_WITH_PRIOR else "user_confirmed_candidate"
        entry = {"number": index, "id": ident, "raw_label": raw, "status": status,
                 "champion": champion, "crop": source["crop"], "training_eligible": False}
        entries.append(entry)
        prefix, crop_id = ident.split("-", 1)
        group = decisions.setdefault(prefix, {"user_confirmed": {}, "assistant_visual_match": {},
                                               "confirmed_non_champion": []})
        if status == "user_confirmed_candidate":
            group["user_confirmed"][crop_id] = champion
        elif status == "not_champion_body":
            group["confirmed_non_champion"].append(crop_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write(args.output_dir / "full-user-review-mapped-20261010.json", {
        "schema_version": 1,
        "source_audit": str(args.frozen_audit),
        "review_tsv": str(args.review_tsv),
        "entries": entries,
        "training_eligible": 0,
    })
    folders = {"E": "elderwood-4k-crops", "F": "firsttime-4k-crops",
               "S": "sivir-1440-crops", "N": "nidalee-1440-crops", "V": "vi-1080-crops"}
    for prefix, group in decisions.items():
        group.update({
            "source_batch": folders[prefix], "id_prefix": prefix,
            "source_manifest": str(args.frozen_audit.parent / folders[prefix] / "review_manifest.json"),
            "training_eligibility": False,
            "note": "Rótulos do usuário numerados no PDF completo; recortes ainda sem aprovação de caixa e pose.",
        })
        write(args.output_dir / f"review_decisions_full_{prefix}_20261010.json", group)
    counts = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
