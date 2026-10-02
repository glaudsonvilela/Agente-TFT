"""Offline overlay; no unobserved board grid is shown as an established map."""
import base64,json,sys
from pathlib import Path
from training.uimap_path_l3 import legacy
from uimap_lite_l2.common import load,contained,sha,require

records,root,out=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3])
rows=load(records);total=0
for r in rows:
    p=contained(root,r['image']);require(sha(p)==r['sha256'],'viewer image changed')
    b=p.read_bytes();total+=len(b);require(total<80*1024**2,'viewer image budget')
    r['uri']='data:image/jpeg;base64,'+base64.b64encode(b).decode('ascii')
payload=json.dumps(rows,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
page='''<!doctype html><meta charset="utf-8"><title>UI-Map L3 — comparação</title>
<style>body{background:#111a26;color:#e2e8f0;font:16px system-ui;margin:20px}canvas{max-width:100%;height:auto}pre{white-space:pre-wrap}button,input{margin:10px}</style>
<h1>L2 × L3 — caminho dos pixels</h1><p>Laranja: L2. Ciano: L3. Tracejado: desconhecido. Caixas são propostas, não recortes aprovados.</p>
<p>Tabuleiro: sem pontos de apoio observados; não se deriva uma grade do retângulo do banco ou da loja.</p>
<button id="prev">Anterior</button><input id="sel" type="range" min="0" value="0"><button id="next">Próximo</button><p id="status"></p><canvas id="canvas"></canvas><pre id="detail"></pre>
<script id="data" type="application/json">PAYLOAD</script><script>
const rows=JSON.parse(document.getElementById('data').textContent),s=document.getElementById('sel'),c=document.getElementById('canvas'),ctx=c.getContext('2d');s.max=rows.length-1;let rev=0;
function draw(){const r=rows[+s.value],ticket=++rev,im=new Image();document.getElementById('status').textContent=`${+s.value+1}/${rows.length} — ${r.timestamp_ms} ms`;document.getElementById('detail').textContent=JSON.stringify({l2:r.l2,l3:r.l3,board:r.board},null,2);im.onload=()=>{if(ticket!==rev)return;c.width=im.width;c.height=im.height;ctx.drawImage(im,0,0);ctx.lineWidth=2;for(const [key,color]of [['l2','#ffbd66'],['l3','#54dbed']]){ctx.strokeStyle=color;for(const p of r[key]){ctx.setLineDash(p.accepted_as_coarse?[]:[6,4]);ctx.strokeRect(...p.box_pixels);}}};im.src=r.uri;}
function move(d){s.value=Math.min(rows.length-1,Math.max(0,+s.value+d));draw();}document.getElementById('prev').onclick=()=>move(-1);document.getElementById('next').onclick=()=>move(1);s.oninput=draw;draw();
</script>'''
with out.open('x') as f:f.write(page.replace('PAYLOAD',payload))
