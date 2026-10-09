"""Show the ongoing expert-video review in an Ubuntu terminal tab.

Only game-related speech is displayed as a possible coaching example. General
conversation and uncertain transcription are counted, not called learning.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def follow(path: Path) -> None:
    seen = 0
    relevant = 0
    general = 0
    print("AGENTE TFT | Revisão de 2.000 momentos de jogadores de alto nível", flush=True)
    print("Original + tradução automática. Estratégia e jogada ainda exigem revisão visual.\n", flush=True)
    while not path.exists():
        time.sleep(0.5)
    with path.open(encoding="utf-8") as stream:
        while True:
            line = stream.readline()
            if not line:
                time.sleep(0.5)
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            seen += 1
            themes = [theme for theme in row["themes"] if theme != "contexto_geral"]
            if not themes:
                general += 1
                if seen % 50 == 0:
                    print(f"PROGRESSO {seen}/2000 | {relevant} possíveis momentos de jogo | "
                          f"{general} falas gerais separadas\n", flush=True)
                continue
            relevant += 1
            print(f"[{row['moment']:04d}/2000] {row['source_kind'].upper()} "
                  f"{row['start']/60:.1f} min | {', '.join(themes)}", flush=True)
            print(f"  Original: {row['phrase_en']}", flush=True)
            print(f"  Português automático: {row['phrase_pt_br']}", flush=True)
            print("  IA registrou: contexto da fala; decisão e resultado ainda não confirmados.\n", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("translated_moments", type=Path)
    args = parser.parse_args()
    follow(args.translated_moments)


if __name__ == "__main__":
    main()
