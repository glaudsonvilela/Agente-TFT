"""Self-contained offline comparison. Coordinates are screen boxes, not reconstructed 3D."""
import base64
import json
from training.board_detector_core import require


def write_viewer(path, records, root):
    from training.board_spatial_run import source_path
    rows = []
    for r in records:
        image = source_path(root, r['image'])
        mime = 'image/png' if image.suffix.lower()=='.png' else 'image/jpeg'
        rows.append(dict(timestamp_ms=r['timestamp_ms'], b1=r['b1']['markers'], nn=r['neural']['proposals'],
            comparison=r['comparison'], projection=r['b1']['projection_status'],
            uri='data:'+mime+';base64,'+base64.b64encode(image.read_bytes()).decode('ascii')))
    payload = json.dumps(rows, ensure_ascii=True)
    for character, escape in [('<', 'u003c'), ('>', 'u003e'), ('&', 'u0026')]:
        payload = payload.replace(character, chr(92)+escape)
    require(len(payload) <= 96*1024*1024, 'viewer byte budget exceeded')
    page = '''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>B3 — B1 × detector visual</title><style>
body{margin:20px;background:#101722;color:#e2e8f0;font:16px system-ui}button,input{margin:8px}canvas{max-width:100%;height:auto}pre{white-space:pre-wrap}strong{color:#ffd95a}</style>
<h1>B1 × detector visual — teste local</h1><p><strong>Caixas não comprovam ocupação, identidade ou posição 3D. Mais caixas não significa mais acertos.</strong></p>
<button id="prev">Anterior</button><input id="index" type="range" min="0" value="0"><button id="next">Próximo</button>
<label><input id="bars" type="checkbox" checked>B1: barras (amarelo)</label><label><input id="neural" type="checkbox" checked>Detector: propostas (ciano)</label>
<p id="status"></p><canvas id="screen"></canvas><pre id="details"></pre>
<script id="data" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),slider=document.getElementById('index');slider.max=data.length-1;
const canvas=document.getElementById('screen'),ctx=canvas.getContext('2d');let revision=0;
function draw(){const ticket=++revision,r=data[+slider.value],im=new Image();
 document.getElementById('status').textContent=`Frame ${+slider.value+1}/${data.length} — ${r.timestamp_ms} ms — B1: ${r.projection}`;
 document.getElementById('details').textContent=JSON.stringify(r.comparison,null,2);
 im.onload=()=>{if(ticket!==revision)return;canvas.width=im.naturalWidth;canvas.height=im.naturalHeight;ctx.drawImage(im,0,0);ctx.lineWidth=2;ctx.font='18px monospace';
 function box(d,color,text){const b=d.rect;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.strokeRect(b.x,b.y,b.width,b.height);ctx.fillText(text,b.x,Math.max(20,b.y-4));}
 if(document.getElementById('bars').checked)r.b1.forEach(d=>box(d,'#ffdc67',`B1 ${d.id}`));
 if(document.getElementById('neural').checked)r.nn.forEach(d=>box(d,'#58e6ff',`NN ${d.id} ${d.score.toFixed(2)}`));};im.src=r.uri;}
function move(n){slider.value=Math.max(0,Math.min(data.length-1,+slider.value+n));draw();}
document.getElementById('prev').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);slider.oninput=draw;
['bars','neural'].forEach(id=>document.getElementById(id).onchange=draw);document.onkeydown=e=>{if(e.key==='ArrowLeft')move(-1);if(e.key==='ArrowRight')move(1);};draw();
</script></html>'''
    with path.open('x', encoding='utf-8') as f:
        f.write(page.replace('PAYLOAD', payload))
