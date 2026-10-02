"""Offline side-by-side diagnostic over originals; predictions are not labels."""
import base64,json
from .common import contained,require


def write_viewer(path,records,root):
    data=[]
    for r in records:
        p=contained(root,r['image'])
        data.append(dict(**r,uri='data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode()))
    payload=json.dumps(data,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    require(len(payload)<96*1024**2,'viewer size')
    html='''<!doctype html><meta charset="utf-8"><title>UI-Map Lite L2</title>
<style>body{background:#111a26;color:#e2e8f0;font:16px system-ui;margin:20px}canvas{max-width:100%}pre{white-space:pre-wrap}button,input{margin:10px}</style>
<h1>L1 × L2 — mapa da interface</h1><p>Amarelo: L1. Ciano: L2 espacial. Verde: refinamento aplicado. Linhas tracejadas: desconhecido. Nenhum mapa ativo.</p>
<button id="prev">Anterior</button><input id="sel" type="range" value="0" min="0"><button id="next">Próximo</button><p id="status"></p><canvas id="canvas"></canvas><pre id="detail"></pre>
<script type="application/json" id="data">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),s=document.getElementById('sel'),c=document.getElementById('canvas'),ctx=c.getContext('2d');s.max=data.length-1;let rev=0;
function draw(){const ticket=++rev,r=data[+s.value],im=new Image();document.getElementById('status').textContent=`${+s.value+1}/${data.length}: ${r.timestamp_ms} ms`;document.getElementById('detail').textContent=JSON.stringify({L1:r.l1,L2:r.l2,refinement:r.refinement},null,2);
im.onload=()=>{if(ticket!==rev)return;c.width=im.naturalWidth;c.height=im.naturalHeight;ctx.drawImage(im,0,0);ctx.font='18px monospace';ctx.lineWidth=2;
function boxes(rows,color,label){ctx.strokeStyle=color;ctx.fillStyle=color;rows.forEach(x=>{const b=x.box_pixels;ctx.setLineDash(x.accepted_as_coarse?[]:[8,6]);ctx.strokeRect(...b);ctx.fillText(label+' '+x.panel,b[0],Math.max(20,b[1]-4));});}
boxes(r.l1,'#ffd966','L1');boxes(r.l2,'#67e8f9','L2');boxes(r.refined.filter((_,i)=>r.refinement[i].applied),'#86efac','L2R');};im.src=r.uri;}
function move(n){s.value=Math.max(0,Math.min(data.length-1,+s.value+n));draw();}s.oninput=draw;document.getElementById('prev').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);draw();</script>'''
    path.write_text(html.replace('PAYLOAD',payload))
