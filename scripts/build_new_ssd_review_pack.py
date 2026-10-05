#!/usr/bin/env python3
"""Build a human-review pack from the bounded Sherlock SSD review queue.

This script is display/review only:
- no model inference
- no automatic identity labels
- no training
- no manifest mutation

It creates:
- crop-sheets/page-XX.png (24 candidates/page)
- lux-sheets/page-XX.png (4 context frames/page)
- index.html
- review-decisions-template.json
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

DEFAULT_QUEUE_ROOT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/new-image-review-queue-20261005"
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"REVIEW_PACK_ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


def text_lines(draw, xy, lines, fill, font, spacing=2):
    x, y = xy
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        box = draw.textbbox((x, y), line, font=font)
        y = box[3] + spacing


def short_id(value: str) -> str:
    return value.replace("DA_18_", "").replace("DA_", "").replace("18", "")


def crop_pages(rows: list[dict[str, Any]], out: Path) -> list[str]:
    from PIL import Image, ImageDraw, ImageFont

    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    pages = []
    page_size = 24
    cols, rows_per_page = 6, 4
    cell_w, cell_h = 190, 205
    for page_no, chunk_start in enumerate(range(0, len(rows), page_size), 1):
        chunk = rows[chunk_start : chunk_start + page_size]
        sheet = Image.new("RGB", (cols * cell_w, rows_per_page * cell_h), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(chunk):
            col, rr = i % cols, i // cols
            x, y = col * cell_w, rr * cell_h
            path = Path(str(row["crop_path"]))
            with Image.open(path) as im:
                crop = im.convert("RGB")
                if crop.size != (128, 144):
                    crop.thumbnail((128, 144))
                sheet.paste(crop, (x + 4, y + 35))
            number = int(row["review_number"])
            suggestion = short_id(str(row["target_id_suggestion"]))
            source_new = "NEW SRC" if row.get("new_source_relative_to_current_train") else "same src"
            score = row.get("suggestion_score")
            score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
            text_lines(
                draw,
                (x + 4, y + 4),
                [
                    f"#{number:03d}  {suggestion}",
                    f"{source_new}  score={score_text}",
                ],
                (245, 245, 245),
                font,
            )
        name = f"page-{page_no:02d}.png"
        sheet.save(out / name)
        pages.append(name)
    return pages


def lux_pages(rows: list[dict[str, Any]], out: Path) -> list[str]:
    from PIL import Image, ImageDraw, ImageFont

    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    pages = []
    page_size = 4
    cols, rows_per_page = 2, 2
    thumb_w, thumb_h = 640, 360
    cell_w, cell_h = 660, 410
    for page_no, chunk_start in enumerate(range(0, len(rows), page_size), 1):
        chunk = rows[chunk_start : chunk_start + page_size]
        sheet = Image.new("RGB", (cols * cell_w, rows_per_page * cell_h), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(chunk):
            col, rr = i % cols, i // cols
            x, y = col * cell_w, rr * cell_h
            path = Path(str(row["full_frame_path"]))
            with Image.open(path) as im:
                frame = im.convert("RGB")
                frame.thumbnail((thumb_w, thumb_h))
                sheet.paste(frame, (x + 4, y + 40))
            number = int(row["review_number"])
            seconds = row.get("source_seconds_nominal")
            sec_text = f"{seconds}s" if isinstance(seconds, (int, float)) else "time ?"
            source_new = "NEW SRC" if row.get("new_source_relative_to_current_train") else "same src"
            text_lines(
                draw,
                (x + 4, y + 4),
                [
                    f"LUX #{number:03d}  {sec_text}  {source_new}",
                    str(row.get("source_id", ""))[:80],
                ],
                (245, 245, 245),
                font,
            )
        name = f"page-{page_no:02d}.png"
        sheet.save(out / name)
        pages.append(name)
    return pages


def html_page(
    queue_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    crop_pages_list: list[str],
    lux_pages_list: list[str],
) -> str:
    crop_cards = []
    for row in queue_rows:
        n = int(row["review_number"])
        suggestion = html.escape(str(row["target_id_suggestion"]))
        src = html.escape(str(row.get("source_id", "")))
        sec = html.escape(str(row.get("source_seconds_nominal", "")))
        crop = Path(str(row["crop_path"])).as_uri()
        full = row.get("full_frame_path")
        full_link = (
            f'<a href="{Path(str(full)).as_uri()}">context</a>' if full else "no context frame"
        )
        new_src = "YES" if row.get("new_source_relative_to_current_train") else "no"
        crop_cards.append(
            f"<article><h3>#{n:03d} · {suggestion}</h3>"
            f'<a href="{crop}"><img src="{crop}" width="128" height="144"></a>'
            f"<p>new source: <strong>{new_src}</strong><br>{src}<br>t={sec}</p>"
            f"<p>{full_link}</p></article>"
        )
    lux_cards = []
    for row in context_rows:
        n = int(row["review_number"])
        path = Path(str(row["full_frame_path"])).as_uri()
        src = html.escape(str(row.get("source_id", "")))
        sec = html.escape(str(row.get("source_seconds_nominal", "")))
        new_src = "YES" if row.get("new_source_relative_to_current_train") else "no"
        lux_cards.append(
            f"<article class='wide'><h3>Lux #{n:03d}</h3>"
            f'<a href="{path}"><img src="{path}"></a>'
            f"<p>new source: <strong>{new_src}</strong> · t={sec}<br>{src}</p></article>"
        )
    page_links = "".join(
        f'<a href="crop-sheets/{html.escape(p)}">{html.escape(p)}</a> '
        for p in crop_pages_list
    )
    lux_links = "".join(
        f'<a href="lux-sheets/{html.escape(p)}">{html.escape(p)}</a> '
        for p in lux_pages_list
    )
    return f"""<!doctype html>
<html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agente TFT · Revisão neural</title>
<style>
body{{margin:24px;background:#151515;color:#eee;font:14px system-ui}}
a{{color:#9ecbff}} header{{max-width:1100px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}}
article{{background:#202020;padding:12px;border-radius:8px;overflow-wrap:anywhere}}
article img{{display:block;margin:auto;object-fit:contain;max-width:100%}}
.wide{{grid-column:span 2}} .wide img{{width:640px;height:auto}}
code{{background:#292929;padding:2px 4px}}
</style>
<header>
<h1>Agente TFT · fila de revisão visual</h1>
<p><strong>Não são rótulos.</strong> As sugestões só priorizam o que revisar.
Nenhuma decisão desta página entra no treino automaticamente.</p>
<p>Crops: {len(queue_rows)} · Contextos Lux: {len(context_rows)}</p>
<p>Páginas crops: {page_links}</p>
<p>Páginas Lux: {lux_links}</p>
<p>Preencha depois <code>review-decisions-template.json</code> somente com identidades
visualmente confirmadas.</p>
</header>
<h2>Candidatos de identidade</h2>
<section class="grid">{''.join(crop_cards)}</section>
<h2>Contextos Lux</h2>
<section class="grid">{''.join(lux_cards)}</section>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-root", type=Path, default=DEFAULT_QUEUE_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.queue_root.expanduser().resolve()
    output = (
        args.output.expanduser()
        if args.output
        else root / "review-pack-v1"
    )
    if output.exists():
        die(f"output already exists: {output}")

    queue_doc = load_json(root / "queue.json")
    context_doc = load_json(root / "context.json")
    queue_rows = queue_doc.get("queue")
    context_rows = context_doc.get("rows")
    if not isinstance(queue_rows, list) or not isinstance(context_rows, list):
        die("invalid queue/context documents")

    policy = queue_doc.get("policy", {})
    if policy.get("model_suggestions_are_labels") is not False:
        die("queue policy does not explicitly reject model suggestions as labels")
    if policy.get("automatic_admission_to_training") is not False:
        die("queue policy permits automatic training admission")
    if policy.get("minjo_kh_allowed_in_training") is not False:
        die("Minjo/KH training exclusion is not preserved")

    output.mkdir(parents=True)
    crop_names = crop_pages(queue_rows, output / "crop-sheets")
    lux_names = lux_pages(context_rows, output / "lux-sheets")

    decisions = {
        "schema_version": 1,
        "kind": "manual_visual_review_decisions",
        "queue_source": str(root / "queue.json"),
        "policy": {
            "model_prediction_used_as_label": False,
            "automatic_training_admission": False,
            "ambiguous_is_negative": False,
            "runtime_approved": False,
        },
        "crop_decisions": [
            {
                "review_number": row["review_number"],
                "suggested_id_for_priority_only": row["target_id_suggestion"],
                "decision": None,
                "confirmed_id": None,
                "review_basis": None,
                "notes": None,
            }
            for row in queue_rows
        ],
        "lux_context_decisions": [
            {
                "review_number": row["review_number"],
                "decision": None,
                "confirmed_lux_form": None,
                "review_basis": None,
                "notes": None,
            }
            for row in context_rows
        ],
    }
    (output / "review-decisions-template.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "index.html").write_text(
        html_page(queue_rows, context_rows, crop_names, lux_names),
        encoding="utf-8",
    )
    summary = {
        "crop_candidates": len(queue_rows),
        "crop_sheet_pages": len(crop_names),
        "lux_context_frames": len(context_rows),
        "lux_sheet_pages": len(lux_names),
        "index": str(output / "index.html"),
        "decision_template": str(output / "review-decisions-template.json"),
        "training_performed": False,
        "runtime_approved": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nREVIEW_PACK_OK=true")
    print(f"OUTPUT={output}")
    print(f"INDEX={output / 'index.html'}")
    print(f"CROP_SHEETS={len(crop_names)}")
    print(f"LUX_SHEETS={len(lux_names)}")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
