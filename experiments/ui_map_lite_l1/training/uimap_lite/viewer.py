"""One offline contact sheet. Original inputs are retained and never rewritten."""
from __future__ import annotations
import base64
import io
from PIL import Image, ImageDraw
from .common import contained


def write_viewer(path, root, records):
    cells=[]
    for record in records:
        with Image.open(contained(root,record['image'])) as source:
            im=source.convert('RGB').resize((640,360))
        draw=ImageDraw.Draw(im)
        for p in record['panels']:
            x,y,w,h=p['box_pixels']
            color='#4dcbe8' if p['state']=='candidate' else '#ffb347'
            draw.rectangle([x/3,y/3,(x+w)/3,(y+h)/3],outline=color,width=2)
            draw.text((max(0,x/3),max(0,y/3-12)),p['panel']+' '+p['state'],fill=color)
        data=io.BytesIO();im.save(data,format='JPEG',quality=84)
        uri='data:image/jpeg;base64,'+base64.b64encode(data.getvalue()).decode()
        cells.append(f'<figure><figcaption>{record["timestamp_ms"]} ms</figcaption><img src="{uri}" alt="coarse predicted panels"></figure>')
    text='''<!doctype html><meta charset="utf-8"><title>UI-Map Lite L1</title>
<style>body{background:#141923;color:#eee;font:16px system-ui;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:12px}figure{margin:0}img{width:100%}</style>
<h1>UI-Map Lite L1 — diagnóstico</h1><p>Retângulos aproximados; não são recortes seguros para OCR nem posições de unidades. Ciano: proposta; laranja: desconhecido. Nenhum perfil ativo alterado.</p><main>'''+''.join(cells)+'</main>'
    with path.open('x',encoding='utf-8') as f:f.write(text)
