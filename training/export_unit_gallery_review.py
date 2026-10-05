"""Export reviewed training crops with stable image codes and catalog identities.

This is an inspection artifact, not new ground truth or model predictions.
Raw video frames and crops remain in the private dataset/laboratory directory.
"""

import argparse
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urlparse

from training.train_unit_identity import samples


def crop_code(pixel_sha256, box):
    # Identity-independent: correcting a name must not change the image code.
    payload = json.dumps([pixel_sha256, box], separators=(",", ":")).encode()
    return "U-" + hashlib.sha256(payload).hexdigest()[:20]


def export(args):
    from PIL import Image

    if args.output.exists():
        raise ValueError("Use a new output directory")
    document = json.loads(args.annotations.read_text(encoding="utf-8"))
    reference = json.loads(
        (args.reference / "reference.json").read_text(encoding="utf-8")
    )
    raw = (args.reference / "champions.json").read_bytes()
    if (
        hashlib.sha256(raw).hexdigest()
        != reference["components"]["champions"]["sha256"]
    ):
        raise ValueError("Catalog hash mismatch")
    catalog = json.loads(raw)
    records = samples(document, args.images, catalog, reference["reference_sha256"])
    frames = {f["sha256"]: f for f in document["frames"]}
    names = {e["id"]: e["name"] for e in catalog["entries"]}
    records = sorted(
        (r for r in records["train"] if r["label"] != "__unknown__"),
        key=lambda r: (names[r["label"]], r["image"], r["key"]),
    )
    (args.output / "crops").mkdir(parents=True)
    index, cards, codes = [], [], set()
    for row in records:
        frame = frames[row["frame_sha256"]]
        code = crop_code(frame["pixel_sha256"], row["box"])
        if code in codes:
            raise ValueError("Duplicate crop code")
        codes.add(code)
        filename = f"crops/{code}.png"
        with Image.open(args.images / row["image"]) as image:
            image.convert("RGB").crop(row["box"]).save(args.output / filename)
        item = dict(
            number=len(index) + 1,
            code=code,
            unit_id=row["label"],
            name=names[row["label"]],
            image=filename,
            crop_sha256=hashlib.sha256(
                (args.output / filename).read_bytes()
            ).hexdigest(),
            source_image=row["image"],
            source_frame_sha256=frame["sha256"],
            source_ms=frame["source_ms"],
            source_url=frame.get("source_url"),
            box=row["box"],
            set_key=catalog["set_key"],
            partition="train",
            review_status="assistant_reviewed_not_independent_ground_truth",
            identity_verified=False,
        )
        index.append(item)
        source = item["source_url"] or ""
        parsed = urlparse(source)
        link = ""
        if parsed.scheme == "https" and parsed.hostname in (
            "www.youtube.com",
            "www.twitch.tv",
            "youtube.com",
            "twitch.tv",
        ):
            link = f'<a href="{html.escape(source, quote=True)}" rel="noreferrer">Vídeo de origem</a>'
        fields = " ".join((item["name"], item["unit_id"], code, item["source_image"]))
        cards.append(
            f'<article data-search="{html.escape(fields.casefold(), quote=True)}">'
            f'<a href="{filename}"><img loading="lazy" src="{filename}" '
            f'width="128" height="144" alt="{html.escape(item["name"], quote=True)}"></a>'
            f'<h2>{item["number"]:03} · {html.escape(item["name"])}</h2>'
            f'<code>{code}</code><p>{html.escape(item["unit_id"])}</p>'
            f'<small>{html.escape(item["source_image"])} · '
            f'{item["source_ms"] / 1000:.1f}s</small><p>{link}</p></article>'
        )
    (args.output / "index.json").write_text(
        json.dumps(dict(schema_version=1, samples=index), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    page = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agente TFT · Galeria visual</title><style>
body{margin:32px;background:#f3f0fb;color:#211738;font:16px system-ui}
h1{margin-bottom:8px}header{max-width:1000px}input{padding:12px;width:min(90%,560px);
border:1px solid #b2a2d1;border-radius:8px;font:inherit;margin:16px 0 24px}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(235px,1fr));gap:16px}
article{background:white;border:1px solid #ded4ee;border-radius:12px;padding:16px;
overflow-wrap:anywhere}article[hidden]{display:none}img{display:block;margin:auto;
object-fit:contain;background:#201929}h2{font-size:17px}p{font-size:13px}small,code{
font-size:11px}a{color:#583895}footer{margin:24px 0}</style>
<header><h1>Agente TFT · Galeria visual</h1><p>__COUNT__ recortes · __IDS__ IDs.
Cada imagem tem um código estável, separado do ID oficial do campeão.</p>
<p>Rótulos revisados pelo assistente. Ainda não são validação independente nem
identidades confirmadas pelo software. Somente exemplos de treino aparecem aqui.</p>
<input id="search" aria-label="Filtrar por nome, código ou origem"
placeholder="Buscar campeão, código, YouTube ou Twitch"><p id="count"></p></header>
<main>__CARDS__</main><footer><a href="index.json">Baixar índice com códigos e rótulos</a>
 · Clique numa imagem para abrir o recorte original.</footer><script>
const input=document.querySelector('#search'),cards=[...document.querySelectorAll('article')];
function filter(){const q=input.value.toLocaleLowerCase();let n=0;
for(const card of cards){card.hidden=!card.dataset.search.includes(q);if(!card.hidden)n++;}
document.querySelector('#count').textContent=n+' recortes exibidos';}
input.addEventListener('input',filter);filter();</script></html>"""
    page = (
        page.replace("__COUNT__", str(len(index)))
        .replace("__IDS__", str(len({r["unit_id"] for r in index})))
        .replace("__CARDS__", "".join(cards))
    )
    (args.output / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps(dict(crops=len(index), output=str(args.output))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("annotations", "images", "reference", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    export(parser.parse_args())
