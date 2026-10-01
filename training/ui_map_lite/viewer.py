"""Offline region-proposal viewer; no external scripts/plugins/network/annotation service."""
import base64
import json
from .core import require, inside


def write_viewer(path, records, root, boxes):
    rows=[]
    for r in records:
        image=inside(root,r['image'])
        rows.append(dict(timestamp_ms=r['timestamp_ms'],proposals=r['regions'],
            uri=('data:image/png;base64,' if image.suffix.lower()=='.png' else 'data:image/jpeg;base64,')+base64.b64encode(image.read_bytes()).decode('ascii')))
    payload=json.dumps(dict(rows=rows,baseline=boxes),ensure_ascii=True)
    payload=payload.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    require(len(payload)<96*1024**2,'viewer budget')
    html='''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>UI-Map Lite U1</title>
<style>body{font:16px system-ui;background:#14202b;color:#eef;padding:18px}canvas{max-width:100%;height:auto}pre{white-space:pre-wrap}</style>
<h1>UI-Map Lite — propostas, não perfil ativo</h1><p>Ciano: rede. Amarelo: recortes fixos históricos. Inferência real sem rótulos; não é acurácia.</p>
<button id="prev">Anterior</button><input id="index" type="range" value="0" min="0"><button id="next">Próximo</button>
<p id="status"></p><canvas id="screen"></canvas><pre id="details"></pre>
<script type="application/json" id="data">PAYLOAD</script><script>
const d=JSON.parse(document.getElementById('data').textContent),s=document.getElementById('index'),c=document.getElementById('screen'),ctx=c.getContext('2d');s.max=d.rows.length-1;let rev=0;
function show(){let ticket=++rev,r=d.rows[+s.value],im=new Image();document.getElementById('status').textContent=r.timestamp_ms+' ms';document.getElementById('details').textContent=JSON.stringify(r.proposals,null,2);
im.onload=()=>{if(ticket!==rev)return;c.width=im.naturalWidth;c.height=im.naturalHeight;ctx.drawImage(im,0,0);ctx.lineWidth=3;
ctx.strokeStyle='#eed564';d.baseline.forEach(b=>ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]));
ctx.strokeStyle='#64e3ee';r.proposals.forEach(p=>{if(!p.corners_px)return;let a=p.corners_px[0],b=p.corners_px[2];ctx.strokeRect(a[0],a[1],b[0]-a[0],b[1]-a[1]);});};im.src=r.uri;}
function move(k){s.value=Math.max(0,Math.min(d.rows.length-1,+s.value+k));show();}s.oninput=show;
document.getElementById('prev').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);show();</script></html>'''
    with path.open('x',encoding='utf-8') as f:f.write(html.replace('PAYLOAD',payload))
