"""Explain the visual-context experiment in Portuguese in the Ubuntu terminal.

The English speech and automatic translation are supporting context only;
visual change scores and held-out retrieval are the actual measured results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.show_expert_learning_pt import translator


def show(run: Path, triplets: Path, moments: Path, limit: int,
         review_queue: Path | None = None) -> None:
    report = json.loads((run / "report.json").read_text())
    changes_path = review_queue or run / "visual_change_candidates.jsonl"
    changes = [json.loads(line) for line in changes_path.open()]
    clips = {row["moment"]: row for row in (json.loads(line) for line in triplets.open())}
    speech = {row["moment"]: row for row in (json.loads(line) for line in moments.open())}
    model, language = translator()
    print("AGENTE TFT | O que o modelo visual observou", flush=True)
    print(f"1.000 sequências vistas. Vídeo separado: {report['baseline_correct']}/{report['held_out_pairs']} "
          f"antes; {report['final_correct']}/{report['held_out_pairs']} depois.", flush=True)
    print("Tradução automática; fala não vira rótulo de jogada. "
          "Mudança visual não prova uma ação do jogador.\n", flush=True)
    if review_queue:
        print(f"Janelas com loja e tabuleiro para revisar: {len(changes)}. "
              "Ações confirmadas: 0.\n", flush=True)
    chosen = []
    for row in changes:
        passage = speech[row["moment"]]
        if not review_queue and set(passage["themes"]) == {"contexto_geral"}:
            continue
        if any(other["source_sha256"] == row["source_sha256"] and
               abs(other["source_seconds"] - row["source_seconds"]) < 90
               for other in chosen):
            continue
        chosen.append(row)
        if len(chosen) == limit:
            break
    for number, row in enumerate(chosen, 1):
        passage = speech[row["moment"]]
        english = passage["phrase_en"]
        translated = model.translate(english)
        changed = row["region_change"]
        biggest = max(changed, key=changed.get)
        print(f"[{number}/{len(chosen)}] Momento {row['moment']} | "
              f"{row['source_seconds']/60:.1f} min | mudança maior: {biggest}", flush=True)
        print(f"  Original: {english}", flush=True)
        print(f"  Português automático ({language}): {translated}", flush=True)
        print("  Mudança visual: " + ", ".join(f"{key}={value:.2f}"
                                                 for key, value in changed.items()), flush=True)
        print("  Aprendizado medido: proximidade entre os três quadros; "
              "ação ainda desconhecida.", flush=True)
        print("  Quadros: " + " | ".join(clips[row["moment"]]["images"][role]
                                          for role in ("before", "during", "after")) + "\n", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--triplets", type=Path, required=True)
    parser.add_argument("--moments", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--review-queue", type=Path)
    args = parser.parse_args()
    show(args.run, args.triplets, args.moments, args.limit, args.review_queue)


if __name__ == "__main__":
    main()
