from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from training.replay_intake import validate_annotations


HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agente TFT — Replay Labeler</title>
<style>
:root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin:0; background:#0d1117; color:#e6edf3; }
header { position:sticky; top:0; z-index:5; display:flex; gap:12px; align-items:center; padding:12px 16px; background:#161b22; border-bottom:1px solid #30363d; }
button, select, input, textarea { background:#0d1117; color:#e6edf3; border:1px solid #30363d; border-radius:6px; padding:8px; }
button { cursor:pointer; }
button:hover { border-color:#8b949e; }
#status { margin-left:auto; font-size:13px; color:#8b949e; }
main { display:grid; grid-template-columns:minmax(0,1fr) 390px; min-height:calc(100vh - 58px); }
.viewer { padding:16px; display:flex; align-items:flex-start; justify-content:center; overflow:auto; }
.viewer img { max-width:100%; max-height:calc(100vh - 95px); border:1px solid #30363d; border-radius:8px; }
.panel { border-left:1px solid #30363d; padding:16px; overflow:auto; max-height:calc(100vh - 58px); }
h2 { margin:0 0 8px; font-size:18px; }
.meta { color:#8b949e; font-size:13px; margin-bottom:14px; }
label { display:block; font-size:12px; color:#8b949e; margin:10px 0 4px; }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.grid5 { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; }
input, select, textarea { width:100%; }
textarea { min-height:72px; resize:vertical; }
.help { color:#8b949e; font-size:12px; line-height:1.4; margin-top:14px; }
.badge { display:inline-block; padding:3px 7px; border-radius:999px; background:#21262d; color:#c9d1d9; font-size:12px; }
.ok { color:#3fb950 !important; }
.err { color:#f85149 !important; }
.warn { color:#d29922 !important; }
.suggest { margin:0 0 14px; padding:10px; border:1px solid #30363d; border-radius:8px; background:#161b22; }
.suggest h3 { margin:0 0 8px; font-size:14px; }
.srow { display:flex; justify-content:space-between; gap:8px; padding:4px 0; font-size:12px; border-top:1px solid #21262d; }
.srow:first-of-type { border-top:0; }
.conf { color:#8b949e; white-space:nowrap; }
@media(max-width:980px) {
  main { grid-template-columns:1fr; }
  .panel { border-left:0; border-top:1px solid #30363d; max-height:none; }
  .viewer img { max-height:none; }
}
</style>
</head>
<body>
<header>
  <button id="prev">← Anterior</button>
  <button id="next">Próximo →</button>
  <span id="counter" class="badge">0 / 0</span>
  <button id="save">Salvar</button>
  <span id="status">carregando…</span>
</header>
<main>
  <section class="viewer"><img id="frameImage" alt="frame do replay"></section>
  <aside class="panel">
    <h2 id="frameTitle">Frame</h2>
    <div id="frameMeta" class="meta"></div>

    <div id="suggestBox" class="suggest" style="display:none">
      <h3>Pré-anotação IA</h3>
      <div id="suggestRows"></div>
      <button id="applySuggestions" type="button">Aplicar sugestões visíveis</button>
      <div class="help">Sugestões não são ground truth. Revise antes de salvar.</div>
    </div>

    <label>Cena</label>
    <select id="scene">
      <option value="">— não classificada —</option>
      <option value="planning_shop">planning/shop</option>
      <option value="board_bench">board/bench</option>
      <option value="scouting_opponents">scouting/oponentes</option>
      <option value="augment">augment</option>
      <option value="transition">transição</option>
      <option value="combat">combate</option>
      <option value="other">outra</option>
    </select>

    <div class="grid2">
      <div><label>HP</label><input id="hp" type="number" min="0"></div>
      <div><label>Gold</label><input id="gold" type="number" min="0"></div>
      <div><label>Level</label><input id="level" type="number" min="1"></div>
      <div><label>XP</label><input id="xp" type="number" min="0"></div>
    </div>

    <label>Stage (ex.: 4-2)</label>
    <input id="stage" placeholder="4-2">

    <label>Shop — 5 slots (ID/nome visível; deixe vazio se desconhecido)</label>
    <div class="grid5">
      <input class="shop" data-slot="0" placeholder="1">
      <input class="shop" data-slot="1" placeholder="2">
      <input class="shop" data-slot="2" placeholder="3">
      <input class="shop" data-slot="3" placeholder="4">
      <input class="shop" data-slot="4" placeholder="5">
    </div>

    <label>Board — IDs/nomes separados por vírgula</label>
    <textarea id="board" placeholder="unit_a, unit_b, unit_c"></textarea>

    <label>Lobby/scouting — player IDs/nomes separados por vírgula</label>
    <textarea id="lobby" placeholder="player_2, player_3"></textarea>

    <div class="help">
      Preencha <strong>somente o que está visualmente confirmado</strong>.
      Campos vazios não entram na métrica de accuracy. Use ←/→ para navegar e Ctrl+S para salvar.
      O arquivo é salvo atomicamente e a versão anterior fica em <code>annotations.json.bak</code>.
    </div>
  </aside>
</main>
<script>
let data = null;
let prelabels = null;
let index = 0;
let dirty = false;

const $ = id => document.getElementById(id);
const intOrNull = id => {
  const v = $(id).value.trim();
  if (v === "") return null;
  const n = Number(v);
  return Number.isInteger(n) ? n : null;
};
const csv = id => $(id).value.split(",").map(x => x.trim()).filter(Boolean);

function setStatus(text, cls="") {
  $("status").className = cls;
  $("status").textContent = text;
}

function current() { return data.frames[index]; }

function currentPrelabel() {
  if (!prelabels || !prelabels.frames) return null;
  const f = current();
  return prelabels.frames.find(p =>
    p.timestamp_ms === f.timestamp_ms && p.image === f.image
  ) || null;
}

function suggestionValueText(value) {
  if (Array.isArray(value)) return value.map(v => v ?? "?").join(", ");
  return String(value);
}

function renderSuggestions() {
  const p = currentPrelabel();
  const box = $("suggestBox");
  const rows = $("suggestRows");
  rows.innerHTML = "";
  if (!p || !p.suggestions || Object.keys(p.suggestions).length === 0) {
    box.style.display = "none";
    return;
  }
  box.style.display = "block";
  for (const [field, item] of Object.entries(p.suggestions)) {
    if (!item || item.value === undefined) continue;
    const row = document.createElement("div");
    row.className = "srow";
    const value = document.createElement("span");
    value.textContent = field + ": " + suggestionValueText(item.value);
    const confidence = document.createElement("span");
    confidence.className = "conf";
    confidence.textContent = Math.round(Number(item.confidence || 0) * 100) + "%";
    row.append(value, confidence);
    rows.appendChild(row);
  }
}

function applySuggestions() {
  const p = currentPrelabel();
  if (!p || !p.suggestions) return;
  const s = p.suggestions;
  if (s.scene) $("scene").value = s.scene.value ?? "";
  for (const key of ["hp","gold","level","xp","stage"]) {
    if (s[key]) $(key).value = s[key].value ?? "";
  }
  if (s.shop && Array.isArray(s.shop.value)) {
    document.querySelectorAll(".shop").forEach((el,i) => el.value = s.shop.value[i] ?? "");
  }
  if (s.board_unit_ids && Array.isArray(s.board_unit_ids.value)) {
    $("board").value = s.board_unit_ids.value.join(", ");
  }
  if (s.lobby_player_ids && Array.isArray(s.lobby_player_ids.value)) {
    $("lobby").value = s.lobby_player_ids.value.join(", ");
  }
  collect();
}

function writeField(frame, key, value) {
  if (value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
    delete frame[key];
  } else {
    frame[key] = value;
  }
}

function collect() {
  if (!data) return;
  const f = current();
  writeField(f, "scene", $("scene").value);
  for (const key of ["hp","gold","level","xp"]) writeField(f, key, intOrNull(key));
  writeField(f, "stage", $("stage").value.trim());

  const shopValues = [...document.querySelectorAll(".shop")].map(x => x.value.trim());
  const anyShop = shopValues.some(Boolean);
  if (anyShop) f.shop = shopValues.map(x => x || null); else delete f.shop;

  writeField(f, "board_unit_ids", csv("board"));
  writeField(f, "lobby_player_ids", csv("lobby"));
  dirty = true;
  setStatus("alterações não salvas", "warn");
}

function fill() {
  const f = current();
  $("counter").textContent = (index + 1) + " / " + data.frames.length;
  $("frameTitle").textContent = "Frame " + String(index + 1).padStart(2,"0");
  $("frameMeta").textContent = "timestamp: " + f.timestamp_ms + " ms • " + f.image;
  $("frameImage").src = "/frame/" + encodeURIComponent(f.image.replace(/^frames\//,""));

  $("scene").value = f.scene || "";
  for (const key of ["hp","gold","level","xp","stage"]) $(key).value = f[key] ?? "";

  const shops = f.shop || [];
  document.querySelectorAll(".shop").forEach((el,i) => el.value = shops[i] ?? "");
  $("board").value = (f.board_unit_ids || []).join(", ");
  $("lobby").value = (f.lobby_player_ids || []).join(", ");
  renderSuggestions();
}

async function save() {
  collect();
  setStatus("salvando…");
  const response = await fetch("/api/annotations", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(data)
  });
  const payload = await response.json();
  if (!response.ok) {
    setStatus("erro ao salvar", "err");
    alert(JSON.stringify(payload, null, 2));
    return;
  }
  dirty = false;
  const warnings = payload.warnings?.length || 0;
  setStatus("salvo" + (warnings ? " • " + warnings + " aviso(s)" : ""), warnings ? "warn" : "ok");
}

function move(delta) {
  collect();
  index = Math.max(0, Math.min(data.frames.length - 1, index + delta));
  fill();
}

async function init() {
  const [annotationResponse, prelabelResponse] = await Promise.all([
    fetch("/api/annotations"),
    fetch("/api/prelabels")
  ]);
  data = await annotationResponse.json();
  prelabels = prelabelResponse.ok ? await prelabelResponse.json() : null;
  if (!data.frames || !data.frames.length) {
    setStatus("nenhum frame", "err");
    return;
  }
  fill();
  setStatus(prelabels ? "pronto • IA carregada" : "pronto", "ok");
}

["scene","hp","gold","level","xp","stage","board","lobby"].forEach(id => {
  $(id).addEventListener("input", collect);
});
document.querySelectorAll(".shop").forEach(el => el.addEventListener("input", collect));
$("prev").onclick = () => move(-1);
$("next").onclick = () => move(1);
$("save").onclick = save;
$("applySuggestions").onclick = applySuggestions;
document.addEventListener("keydown", ev => {
  if (ev.ctrlKey && ev.key.toLowerCase() === "s") { ev.preventDefault(); save(); return; }
  if (["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName)) return;
  if (ev.key === "ArrowLeft") move(-1);
  if (ev.key === "ArrowRight") move(1);
});
window.addEventListener("beforeunload", ev => {
  if (dirty) { ev.preventDefault(); ev.returnValue = ""; }
});
init().catch(err => { console.error(err); setStatus("falha ao carregar", "err"); });
</script>
</body>
</html>
"""


def load_annotations(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("annotations.json must be a JSON object")
    return value


def atomic_save_annotations(path: Path, value: dict) -> dict:
    report = validate_annotations(
        value,
        annotation_dir=path.parent,
    )
    if report["errors"]:
        raise ValueError(json.dumps(report, ensure_ascii=False))

    backup = path.with_name(path.name + ".bak")
    if path.exists():
        shutil.copy2(path, backup)

    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    return report


def safe_frame_path(annotation_dir: Path, relative_name: str) -> Path | None:
    frames_dir = (annotation_dir / "frames").resolve()
    candidate = (frames_dir / relative_name).resolve()
    try:
        candidate.relative_to(frames_dir)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def make_handler(annotation_path: Path):
    annotation_dir = annotation_path.parent

    class Handler(BaseHTTPRequestHandler):
        server_version = "AgenteTFTReplayLabeler/1"

        def log_message(self, fmt: str, *args) -> None:
            print(f"[replay-labeler] {self.address_string()} - {fmt % args}")

        def send_json(self, value: object, status: int = 200) -> None:
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                payload = HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if parsed.path == "/api/annotations":
                try:
                    self.send_json(load_annotations(annotation_path))
                except Exception as error:
                    self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            if parsed.path == "/api/prelabels":
                prelabels_path = annotation_dir / "prelabels.json"
                if not prelabels_path.is_file():
                    self.send_json({"schema_version": 1, "frames": []}, HTTPStatus.OK)
                    return
                try:
                    value = json.loads(prelabels_path.read_text(encoding="utf-8"))
                    self.send_json(value)
                except Exception as error:
                    self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            if parsed.path.startswith("/frame/"):
                name = unquote(parsed.path[len("/frame/"):])
                file_path = safe_frame_path(annotation_dir, name)
                if file_path is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                payload = file_path.read_bytes()
                mime, _ = mimetypes.guess_type(file_path.name)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/annotations":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_json({"error": "invalid Content-Length"}, HTTPStatus.BAD_REQUEST)
                return
            if length <= 0 or length > 5_000_000:
                self.send_json({"error": "invalid request size"}, HTTPStatus.BAD_REQUEST)
                return

            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("payload must be a JSON object")
                original = load_annotations(annotation_path)
                if value.get("source_video") != original.get("source_video"):
                    raise ValueError("source_video cannot be changed in the labeler")
                original_frames = original.get("frames") or []
                new_frames = value.get("frames") or []
                if len(new_frames) != len(original_frames):
                    raise ValueError("frame count cannot be changed in the labeler")
                for old, new in zip(original_frames, new_frames, strict=True):
                    if old.get("timestamp_ms") != new.get("timestamp_ms") or old.get("image") != new.get("image"):
                        raise ValueError("timestamp_ms/image identity cannot be changed in the labeler")
                report = atomic_save_annotations(annotation_path, value)
            except Exception as error:
                try:
                    detail = json.loads(str(error))
                except json.JSONDecodeError:
                    detail = {"error": str(error)}
                self.send_json(detail, HTTPStatus.BAD_REQUEST)
                return

            self.send_json({
                "ok": True,
                "ready_for_calibration": report["ready_for_calibration"],
                "warnings": report["warnings"],
                "counts": report["counts"],
            })

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local browser UI for annotating Agente TFT replay frames."
    )
    parser.add_argument(
        "annotation_dir",
        type=Path,
        help="directory containing annotations.json and frames/",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    annotation_path = args.annotation_dir / "annotations.json"
    if not annotation_path.is_file():
        raise SystemExit(f"annotations not found: {annotation_path}")

    load_annotations(annotation_path)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(annotation_path))
    print(f"Replay labeler: http://{args.host}:{args.port}")
    print(f"Annotations: {annotation_path}")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
