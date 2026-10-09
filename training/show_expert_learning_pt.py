"""Translate and display expert speech with honest learned-context links.

The terminal shows exactly what was heard, a local automatic translation, and
a nearest passage from the trained context encoder. The link is a learned
speech association, never proof that an action occurred or won a fight.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np


THEMES = {
    "economy": "economia", "composition": "composição", "positioning": "posicionamento",
    "combat": "combate", "items": "itens", "choices": "escolhas", "contexto_geral": "contexto geral",
}
GLOSSARY = {
    "roll": "rolar a loja", "reroll": "rolar a loja", "board": "tabuleiro",
    "augment": "aprimoramento", "carry": "carregador principal",
    "slam": "fechar um item", "econ": "economia", "streak": "sequência de vitórias/derrotas",
}


def translator():
    from argostranslate import translate

    languages = translate.get_installed_languages()
    english = next((lang for lang in languages if lang.code == "en"), None)
    portuguese = next((lang for lang in languages if lang.code in {"pt_br", "pt-BR", "pt"}), None)
    if english is None or portuguese is None:
        raise RuntimeError("install an offline English → Portuguese Argos model first")
    return english.get_translation(portuguese), portuguese.code


def related(rows, vectors):
    if len(rows) != len(vectors):
        raise ValueError("moment/context vector count mismatch")
    similarities = vectors @ vectors.T
    result = []
    for i, row in enumerate(rows):
        active_themes = set(row["themes"]) - {"contexto_geral"}
        if not active_themes:
            result.append(None)
            continue
        similarities[i, i] = -1
        for j, other in enumerate(rows):
            if row["source_sha256"] == other["source_sha256"] and abs(row["start"] - other["start"]) < 60:
                similarities[i, j] = -1
            if not active_themes.intersection(set(other["themes"]) - {"contexto_geral"}):
                similarities[i, j] = -1
        best = int(similarities[i].argmax())
        score = float(similarities[i, best])
        result.append({"moment": rows[best]["moment"], "similarity": round(score, 3)} if score >= 0.6 else None)
    return result


def display(memory: Path, context: Path, output: Path):
    rows = [json.loads(line) for line in (memory / "moments.jsonl").open()]
    vectors = np.load(context / "context_vectors.npy")
    links = related(rows, vectors)
    model, language = translator()
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / "translated_moments.jsonl"
    existing = {}
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            result = json.loads(line)
            existing[result["moment"]] = result
    start = time.perf_counter()
    print(f"AGENTE TFT · {len(rows)} momentos de jogadores de alto nível", flush=True)
    print(f"Tradução local: inglês → português ({language}); associação de contexto treinada no CPU.", flush=True)
    print("Falas e traduções são hipóteses/contexto. Jogada executada: somente após revisão do vídeo.\n", flush=True)
    completed = len(existing)
    translated = sum(result.get("translation_status") != "skipped_non_game_speech"
                     for result in existing.values())
    cache = {}
    with log_path.open("a", encoding="utf-8") as log:
        for row, link in zip(rows, links):
            if row["moment"] in existing:
                continue
            english = row["phrase_en"]
            tactical = bool(set(row["themes"]) - {"contexto_geral"})
            if tactical:
                if english not in cache:
                    cache[english] = model.translate(english)
                portuguese = cache[english]
                translated += 1
            else:
                portuguese = None
            themes = ", ".join(THEMES[t] for t in row["themes"])
            game_terms = [f"{word} = {meaning}" for word, meaning in GLOSSARY.items()
                          if word in english.lower().split()]
            learned = (f"associação com o momento {link['moment']} "
                       f"(semelhança {link['similarity']:.2f})" if link else "sem associação forte")
            result = {**row, "phrase_pt_br": portuguese,
                      "translation_status": ("automatic_offline_unreviewed" if tactical
                                             else "skipped_non_game_speech"),
                      "learned_context_link": link,
                      "executed_action_label": None}
            log.write(json.dumps(result, ensure_ascii=False) + "\n")
            log.flush()
            completed += 1
            if tactical:
                print(f"[{completed:04d}/{len(rows)}] {row['source_kind'].upper()} {row['start']/60:.1f} min | {themes}", flush=True)
                print(f"  Original: {english}", flush=True)
                print(f"  Português (automático): {portuguese}", flush=True)
                if game_terms:
                    print(f"  Termos TFT: {'; '.join(game_terms)}", flush=True)
                print(f"  Contexto associado: {learned}; ação ainda não confirmada.\n", flush=True)
            if completed % 100 == 0:
                elapsed = time.perf_counter() - start
                print(f"PROGRESSO {completed}/{len(rows)} | {translated} falas relacionadas ao jogo traduzidas | {elapsed/60:.1f} min\n", flush=True)
    report = {"moments": len(rows), "translated": translated,
              "translation_language": language,
              "learning": "temporal_speech_context_similarity",
              "learned_links": sum(link is not None for link in links),
              "executed_action_labels": 0, "strategy_policy_trained": False,
              "elapsed_seconds": round(time.perf_counter() - start, 2)}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"CONCLUÍDO · {completed} momentos examinados · {translated} traduções de falas relacionadas ao jogo · nenhuma jogada inventada", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    display(args.memory, args.context, args.output)


if __name__ == "__main__":
    main()
