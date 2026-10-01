"""Self-contained B1 viewer. No server, CDN, external scripts or game hooks."""
import base64
import json
from pathlib import Path


def write_viewer(path: Path, profile: dict, manifest: dict, records: list, root: Path):
    images = []
    total = 0
    for row in manifest['frames']:
        source = (root / row['image']).resolve(strict=True)
        if not source.is_relative_to(root.resolve(strict=True)):
            raise ValueError('viewer source escape')
        content = source.read_bytes()
        total += len(content)
        if total > 64 * 1024 * 1024:
            raise ValueError('viewer image budget exceeded')
        mime = 'image/png' if source.suffix.lower() == '.png' else 'image/jpeg'
        images.append('data:' + mime + ';base64,' + base64.b64encode(content).decode('ascii'))
    data = json.dumps(dict(profile=profile, frames=manifest['frames'], records=records, images=images),
                      ensure_ascii=True, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    with path.open('x', encoding='utf-8') as output:
        output.write(HTML.replace('__DATA__', data))


HTML = '''<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agente TFT | Banco e tabuleiro B1</title>
<style>body{background:#11151d;color:#e4e8ee;font:15px system-ui;margin:20px}h1{font-size:22px}button,input{margin:6px}button{padding:8px 16px}canvas{display:block;width:100%;max-width:1440px;border:1px solid #364152;margin:14px 0}pre{white-space:pre-wrap;font-size:12px;max-height:260px;overflow:auto}.note{color:#b8c3d1;max-width:1100px}#status{font-weight:600}</style>
<h1>Banco e tabuleiro · B1</h1>
<p class="note">Guia das posições, candidatos de barras e comparação visual com uma referência do banco. Não são identidades, ocupação confirmada, vida ou autorização de ação. A arena não determina o jogador. Sem ponto de apoio no chão, nenhuma barra recebe uma célula.</p>
<button id="prev">Anterior</button><input id="slider" type="range" min="0" value="0"><button id="next">Próximo</button>
<label><input id="force" type="checkbox"> Mostrar guia não validado em outra arena</label>
<p id="status"></p><canvas id="canvas"></canvas>
<p class="note">Cruz azul: guia da célula. Contorno amarelo/vermelho: candidato de barra. Banco verde: semelhança com a referência vazia; laranja: candidato ou ambiguidade; cinza: desconhecido. Não encontrar barra não significa ausência de unidade.</p><pre id="details"></pre>
<script id="dataset" type="application/json">__DATA__</script>
<script>
'use strict';
const d=JSON.parse(document.getElementById('dataset').textContent), p=d.profile;
const slider=document.getElementById('slider'), canvas=document.getElementById('canvas'), ctx=canvas.getContext('2d');
canvas.width=p.reference_width;canvas.height=p.reference_height;slider.max=d.frames.length-1;
let generation=0;
function show(){
 const i=Number(slider.value), r=d.records[i].read, token=++generation;
 document.getElementById('status').textContent=`${i+1}/${d.frames.length} · ${r.timestamp_ms} ms · ${r.projection_status} · ${r.markers.length} candidatos de barra`;
 document.getElementById('details').textContent=JSON.stringify({timestamp_ms:r.timestamp_ms,bench:r.bench,markers:r.markers,phase:r.phase,perspective:r.perspective},null,2);
 const image=new Image();image.onload=()=>{
  if(token!==generation)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0);
  ctx.font='16px system-ui';ctx.lineWidth=2;
  if(r.projection_status==='reference_arena_match'||document.getElementById('force').checked){
   for(const c of r.board){const [x,y]=c.screen;ctx.strokeStyle='#55caff';ctx.beginPath();ctx.moveTo(x-9,y);ctx.lineTo(x+9,y);ctx.moveTo(x,y-9);ctx.lineTo(x,y+9);ctx.stroke();ctx.fillStyle='#d8f2ff';ctx.fillText(`${c.row},${c.col}`,x+10,y-8);}
   for(const b of r.bench){ctx.strokeStyle=b.evidence==='empty_reference_match'?'#70df96':b.evidence==='unknown'?'#aab4c5':'#ffb54d';ctx.strokeRect(b.rect.x,b.rect.y,b.rect.width,b.rect.height);ctx.fillStyle=ctx.strokeStyle;ctx.fillText(`B${b.slot}`,b.rect.x+5,b.rect.y+b.rect.height-5);}
  }
  for(const m of r.markers){ctx.strokeStyle=m.color==='red'?'#ff596e':'#ffe373';ctx.strokeRect(m.rect.x-2,m.rect.y-2,m.rect.width+4,m.rect.height+4);ctx.fillStyle=ctx.strokeStyle;ctx.fillText(`#${m.id}`,m.rect.x,m.rect.y-5);}
 };image.src=d.images[i];
}
document.getElementById('prev').onclick=()=>{slider.value=Math.max(0,Number(slider.value)-1);show();};
document.getElementById('next').onclick=()=>{slider.value=Math.min(d.frames.length-1,Number(slider.value)+1);show();};
slider.oninput=show;document.getElementById('force').onchange=show;
document.addEventListener('keydown',e=>{if(e.key==='ArrowLeft')document.getElementById('prev').click();if(e.key==='ArrowRight')document.getElementById('next').click();});show();
</script></html>'''
