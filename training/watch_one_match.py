"""Local, full-video TFT review with live Motor 1 readings and an honest action ledger.

The browser plays the original MP4. A separate worker reads selected frames; slow
OCR cannot freeze or replace the video. Only independently reviewed actions are
called confirmed. Other HUD changes are observations, never expert labels.
"""

from __future__ import annotations

import argparse
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/e1_replay"))
from e1.protocol import NativeWorker  # noqa: E402
from scripts.prepare_tessdata_best import prepare as prepare_ocr  # noqa: E402


HTML = r"""<!doctype html><html lang="pt-br"><meta charset="utf-8">
<title>Agente TFT · partida completa</title>
<style>
body{margin:0;background:#0e1119;color:#d9e2ed;font:14px system-ui;display:grid;grid-template-columns:minmax(0,1fr) 375px;min-height:100vh}
main{padding:12px;min-width:0}aside{border-left:1px solid #344153;padding:14px;overflow:auto;max-height:100vh}
h1{font-size:17px;margin:3px 0 9px}h2{font-size:15px;margin:18px 0 8px}
.video{position:relative;background:#000;line-height:0}video{width:100%;height:auto;display:block}canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.pill{border:1px solid #435062;padding:5px 8px;border-radius:6px}
.status{color:#e7bf74}.good{color:#89d99d}.bad{color:#e88989}small{color:#9aa9bd}
.event{border-top:1px solid #344153;padding:9px 0}.event strong{display:block}.event p{margin:4px 0;color:#b9c9dd}
.meter{background:#273647;height:7px;border-radius:5px;overflow:hidden}.meter b{display:block;height:100%;background:#69b7d7;width:0}
code{color:#b1e5cc}button{background:#23344a;color:#fff;border:1px solid #52718d;border-radius:5px;padding:6px;cursor:pointer}
</style><main><h1>Partida completa · Setsuko · 1080p original</h1>
<div class="video"><video id="video" controls preload="metadata" src="/video"></video><canvas id="marks" width="1920" height="1080"></canvas></div>
<div class="row"><span class="pill" id="clock">00:00 / 37:00</span><span class="pill" id="read">Leitor: aguardando</span><span class="pill" id="counts">Ações revisadas: 0 / 8</span></div>
<div class="meter"><b id="progress"></b></div>
<p><small>Vídeo integral sem cortes. HUD e barras vêm do Motor 1 em quadros amostrados; caixas indicam localização, não identificação de campeão. Leitura ausente fica “?”. Ações sem evidência suficiente não viram treino.</small></p>
<h2>O que foi observado</h2><div id="observations"></div></main>
<aside><h1>Motor 1 → registro → Motor 2</h1><div id="hud" class="row"></div>
<div class="row"><span class="pill" id="shop">Loja: ?</span><span class="pill" id="bars">Barras: ?</span></div>
<h2>Aprendizado da partida</h2><p id="learning" class="status">Aguardando ação confirmada e estado anterior/posterior.</p>
<p><small>“Por que” significa relação observável com estado e regras; intenção do jogador e vantagem futura exigem validação adicional.</small></p>
<h2>Eventos confirmados</h2><div id="events"></div>
<h2>Cobertura</h2><div id="coverage"></div></aside>
<script>
const v=document.getElementById('video'),cv=document.getElementById('marks'),ctx=cv.getContext('2d');
function fmt(t){return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0')}
function paint(s){ctx.clearRect(0,0,1920,1080);if(!s)return;
 const boxes=[[760,3,60,34,'estágio'],[1023,881,42,35,'ouro'],[390,884,29,28,'nível'],[460,882,65,30,'XP']];
 ctx.font='19px monospace';ctx.lineWidth=2;
 for(const [x,y,w,h,label] of boxes){ctx.strokeStyle='#f5c968';ctx.strokeRect(x,y,w,h);ctx.fillStyle='#f5c968';ctx.fillText(label,x,y<50?y+h+22:y-5)}
 for(const m of (s.markers||[])){let x=m.x??m.center_x??m.cx,y=m.y??m.center_y??m.cy;if(x==null||y==null)continue;
 ctx.strokeStyle='#68dba7';ctx.beginPath();ctx.arc(x,y,12,0,Math.PI*2);ctx.stroke()}
}
let busy=false,lastSecond=-1;
async function update(){if(busy)return;const second=Math.floor(v.currentTime);if(second===lastSecond&&!v.paused)return;lastSecond=second;busy=true;
 try{const r=await fetch('/api/status?t='+v.currentTime.toFixed(3));const x=await r.json();const s=x.state;
 document.getElementById('clock').textContent=fmt(v.currentTime)+' / '+fmt(v.duration||2220);
 document.getElementById('progress').style.width=(100*v.currentTime/(v.duration||2220))+'%';
 document.getElementById('read').textContent=s?'Leitor: '+fmt(s.source_ms/1000)+(v.currentTime-s.source_ms/1000>3?' · atrasado':''):'Leitor: aguardando';
 document.getElementById('counts').textContent='Ações revisadas: '+x.confirmed_so_far+' / '+x.confirmed_total;
 document.getElementById('hud').innerHTML=['stage','gold','level','xp'].map(k=>'<span class="pill">'+k.toUpperCase()+': '+(s?.hud?.[k]??'?')+'</span>').join('');
 document.getElementById('shop').textContent='Loja: '+(s?.shop_names?.length?s.shop_names.join(' · '):'?');
 document.getElementById('bars').textContent='Barras: '+(s?.marker_count??'?')+' (identidade pendente)';
 document.getElementById('events').innerHTML=x.events.map(e=>'<div class="event"><strong>'+fmt(e.time_ms/1000)+' · '+e.title+'</strong><p>'+e.description+'</p><small>'+e.status+'</small></div>').join('')||'<small>Nenhuma ação revisada até este ponto.</small>';
 document.getElementById('learning').textContent=x.learning||'Aguardando ação confirmada e estado anterior/posterior.';
 document.getElementById('observations').innerHTML=x.observations.map(e=>'<div class="event">'+fmt(e.time_ms/1000)+' · '+e.description+'</div>').join('')||'<small>Aguardando leitura.</small>';
 document.getElementById('coverage').innerHTML='<p>Quadros da fonte: 133.374 (60 fps).<br>Quadros com HUD lido nesta execução: '+x.read_count+'.<br>Ações revisadas em amostra anterior: '+x.confirmed_total+'.<br>Ações não revisadas: muitas; cobertura total de ações ainda não demonstrada.</p>';
 paint(s);
 }catch(e){document.getElementById('read').textContent='Leitor: erro '+e.message}finally{busy=false}}
v.addEventListener('timeupdate',update);v.addEventListener('seeked',()=>{lastSecond=-1;update()});v.addEventListener('play',update);update();setInterval(update,1000);
</script></html>"""


def reviewed_actions(path: Path) -> list[dict]:
    actions = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if row["evidence_status"] != "reviewed_action":
                continue
            actions.append({"time_ms": row["sampled_after_ms"],
                            "kind": row["action_type"],
                            "details": row["action_details"]})
    return sorted(actions, key=lambda action: action["time_ms"])


def compact_read(answer: dict) -> dict:
    hud = {row["field"]: row.get("value") for row in answer.get("hud", [])}
    board = answer.get("board") or {}
    shop = answer.get("shop") or {}
    names = [row.get("observed_name") for row in shop.get("slots", [])
             if row.get("observed_name")]
    # Bar detections are coordinates only; they do not confer identity or ownership.
    markers = board.get("markers") or []
    return {"source_ms": answer["source_ms"], "hud": hud,
            "shop_names": names, "marker_count": len(markers),
            "markers": markers, "board_status": board.get("projection_status")}


class Study:
    def __init__(self, video: Path, ledger: Path, output: Path):
        self.video, self.output = video, output
        self.actions = reviewed_actions(ledger)
        self.lock = threading.Lock()
        self.requested: int | None = None
        self.states: dict[int, dict] = {}
        self.observations: deque[dict] = deque(maxlen=80)
        self.errors: deque[str] = deque(maxlen=8)
        self.stop = threading.Event()
        output.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def request(self, seconds: float):
        if 0 <= seconds <= 2220.1:
            with self.lock:
                key = int(seconds)
                if key not in self.states:
                    self.requested = key

    def _read(self):
        os.environ["TESSDATA_PREFIX"] = str(prepare_ocr())
        os.environ["AGENTE_TFT_RESIDENT_OCR"] = "required"
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        binary = ROOT / "tools/e1-native/target/release/agente-tft-e1-worker"
        capture = cv2.VideoCapture(str(self.video))
        worker = NativeWorker(binary, ROOT / "configs", "tesseract")
        index = 0
        try:
            with (self.output / "motor1-readings.jsonl").open("a", encoding="utf-8") as log:
                while not self.stop.is_set():
                    with self.lock:
                        second, self.requested = self.requested, None
                    if second is None:
                        time.sleep(.05)
                        continue
                    capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
                    ok, frame = capture.read()
                    if not ok:
                        continue
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).tobytes()
                    index += 1
                    answer = worker.request(dict(op="frame", id=index, source_ms=second * 1000,
                                                 width=1920, height=1080, bytes=len(rgb)),
                                            rgb, timeout=20)
                    state = compact_read(answer)
                    with self.lock:
                        previous = self.states.get(second - 1)
                        self.states[second] = state
                        if previous:
                            changes = [key for key in ("stage", "gold", "level", "xp")
                                       if previous["hud"].get(key) is not None and
                                       state["hud"].get(key) is not None and
                                       previous["hud"][key] != state["hud"][key]]
                            if changes:
                                detail = ", ".join(f"{key}: {previous['hud'][key]} → {state['hud'][key]}"
                                                   for key in changes)
                                self.observations.append({"time_ms": second * 1000,
                                                          "description": detail + " (mudança; causa não confirmada)"})
                    log.write(json.dumps(state, ensure_ascii=False) + "\n")
                    log.flush()
        except Exception as exc:
            with self.lock:
                self.errors.append(str(exc))
        finally:
            worker.close()
            capture.release()

    def status(self, seconds: float) -> dict:
        with self.lock:
            key = int(seconds)
            near = [number for number in self.states if number <= key and key - number <= 3]
            state = self.states[max(near)] if near else None
            shown = [a for a in self.actions if 0 <= seconds - a["time_ms"] / 1000 <= 150]
            events = []
            for action in shown[-14:]:
                title = {"buy_xp": "comprou XP", "reroll": "atualizou a loja"}.get(
                    action["kind"], action["kind"])
                events.append({"time_ms": action["time_ms"], "title": title,
                               "description": "Ação revisada no vídeo. Contexto do HUD exibido quando lido; "
                                              "motivo estratégico ainda não comprovado.",
                               "status": "revisada · não vinculada a candidato do Motor 2"})
            learning = (f"Observado: {events[-1]['title']} em {int(events[-1]['time_ms']/1000)}s. "
                        "Hipótese para testar: repetir só em estados semelhantes; ainda não é uma regra aprendida."
                        if events else None)
            return {"state": state, "events": events[::-1], "learning": learning,
                    "observations": [row for row in self.observations if row["time_ms"] <= seconds * 1000][-8:][::-1],
                    "confirmed_total": len(self.actions),
                    "confirmed_so_far": sum(a["time_ms"] <= seconds * 1000 for a in self.actions),
                    "read_count": len(self.states), "errors": list(self.errors)}


def serve(study: Study, host: str, port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._bytes(HTML.encode(), "text/html; charset=utf-8")
            elif parsed.path == "/api/status":
                try:
                    seconds = float(parse_qs(parsed.query).get("t", ["0"])[0])
                    if not 0 <= seconds <= 2220.1:
                        raise ValueError("time outside video")
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                study.request(seconds)
                self._bytes(json.dumps(study.status(seconds), ensure_ascii=False).encode(),
                            "application/json")
            elif parsed.path == "/video":
                self._video()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _bytes(self, data: bytes, content_type: str):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _video(self):
            size = study.video.stat().st_size
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            start = int(match.group(1)) if match and match.group(1) else 0
            end = int(match.group(2)) if match and match.group(2) else min(size - 1, start + 1024 * 1024 - 1)
            if start >= size or end < start:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            end = min(size - 1, end)
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            try:
                with study.video.open("rb") as file:
                    file.seek(start)
                    left = end - start + 1
                    while left:
                        block = file.read(min(left, 256 * 1024))
                        if not block:
                            break
                        self.wfile.write(block)
                        left -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):
            if not self.path.startswith("/api/"):
                super().log_message(format, *args)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"VIEWER_READY http://{host}:{port}/", flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    finally:
        study.stop.set()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.video.is_file() or not args.ledger.is_file():
        parser.error("video and reviewed ledger must exist")
    serve(Study(args.video, args.ledger, args.output), "127.0.0.1", args.port)


if __name__ == "__main__":
    main()
