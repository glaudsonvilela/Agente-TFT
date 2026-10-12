"""Review the complete original replay alongside every recorded Motor 1 lane.

The viewer never assigns an identity from an unverified visual candidate. It
shows source-bound observations and the Rust receipt separately from training.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right, insort
import json
from pathlib import Path
from threading import Lock, Event

from training.watch_one_match import serve, reviewed_actions
from training import watch_one_match


STREAMS = {
    "reader": "roi-observations",
    "hub": "board-hub-observations",
    "items": "fast-item-observations",
    "units": "visual-track-observations",
    "traits": "trait-tooltip-observations",
    "selection": "selected-unit-panel-observations",
    "augments": "augment-options-observations",
    "opponent": "opponent-crop-observations",
}

HTML = r"""<!doctype html><html lang="pt-br"><meta charset="utf-8">
<title>Agente TFT · revisão integral do Motor 1</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#11151c;color:#e0e8f1;font:13px system-ui;display:grid;grid-template-columns:minmax(0,1fr) 420px;min-height:100vh}
main{padding:10px;min-width:0}aside{padding:12px;border-left:1px solid #425066;max-height:100vh;overflow:auto}
h1{font-size:16px;margin:5px 0 10px}h2{font-size:14px;border-top:1px solid #354358;padding-top:10px}
.video{position:relative;background:#000;line-height:0}video{width:100%;display:block}canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.row{display:flex;gap:7px;flex-wrap:wrap;margin:9px 0}.pill{border:1px solid #46556a;padding:4px 7px;border-radius:5px}
small{color:#aebbc9}.warn{color:#f4c36d}.bad{color:#fa8181}pre{white-space:pre-wrap;word-break:break-word;font-size:11px;max-height:350px;overflow:auto}
details{border:1px solid #36475b;margin:5px 0;padding:5px}summary{cursor:pointer}.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px}
</style><main><h1>Partida completa · Setsuko · vídeo original 1920×1080</h1>
<div class="video"><video id="video" controls preload="metadata" src="/video"></video><canvas id="marks" width="1920" height="1080"></canvas></div>
<div class="row"><span class="pill" id="clock">00:00 / 37:00</span><span class="pill" id="progress">Leitura: aguardando</span><span class="pill" id="receipt">Motor 2: aguardando</span></div>
<div class="row" id="filters"></div>
<p><small>Linhas em quadros amostrados: ouro, nível, XP, estágio, vida, loja, barras, banco, itens, sinergias, cartas, painel selecionado e adversários. Azul marca a grade própria; vermelho marca a grade inimiga quando visível. Casas desenhadas não significam peças identificadas. “?” significa não lido; contornos de barras não confirmam nomes. Quando a análise ainda não alcançou o ponto do vídeo, nenhum marcador é reaproveitado de um quadro distante.</small></p>
<h2>Leitura atual</h2><div class="row" id="summary"></div><div id="notices"></div>
</main><aside><h1>Motor 1 → Motor 2 · inspeção</h1><div id="lanes" class="grid"></div>
<h2>Nomes captados neste quadro</h2><div class="row" id="names">Nenhum nome captado neste quadro.</div>
<h2>Aprendizado observado</h2><div id="learning">Nenhuma decisão aprendida foi validada.</div>
<p><small>As oito ações previamente revisadas são exemplos de observação, não prova de que todas as ações da partida foram reconhecidas. Uma causa estratégica só pode ser declarada após validar estado anterior, ação e resultado.</small></p>
<h2>Dados completos por camada</h2><div id="raw"></div></aside>
<script>
const v=document.getElementById('video'),canvas=document.getElementById('marks'),ctx=canvas.getContext('2d');
const cats=['HUD','Loja','Barras','Tabuleiro','Banco','Itens','Sinergias','Cartas','Seleção','Adversários','Outros'];
const colors=['#ffd277','#6ed6ff','#8dec9c','#7dd5ec','#b4a2ff','#ff9bdd','#dca8ff','#ffe268','#ffad8b','#ff7b7b','#b7c2d0'];
const laneLabels={reader:'leitor HUD',hub:'HUB completo',items:'itens rápidos (eventos)',
 units:'trilhas visuais',traits:'janelas de sinergia',selection:'painel selecionado',
 augments:'cartas',opponent:'recortes de adversários'};
const enabled={};for(let i=0;i<cats.length;i++){enabled[cats[i]]=true;const lab=document.createElement('label');lab.className='pill';lab.style.color=colors[i];let c=document.createElement('input');c.type='checkbox';c.checked=true;c.onchange=()=>{enabled[cats[i]]=c.checked;paint(last)};lab.append(c,document.createTextNode(cats[i]));document.getElementById('filters').append(lab)}
let last=null,busy=false,previous=-1,autoWaiting=false;
function fmt(t){return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0')}
function category(id){if(id.startsWith('hud.')||id==='player.hp')return'HUD';if(id.startsWith('shop.'))return'Loja';if(id.includes('marker.'))return'Barras';if(id.includes('board.cells'))return'Tabuleiro';if(id.includes('bench.'))return'Banco';if(id.includes('item')||id.includes('inventory.')||id.includes('equipped.'))return'Itens';if(id.includes('trait'))return'Sinergias';if(id.includes('augment'))return'Cartas';if(id.includes('selected'))return'Seleção';if(id.includes('opponent'))return'Adversários';return'Outros'}
function paint(x){last=x;ctx.clearRect(0,0,1920,1080);if(!x||x.gameplay_started_at===null||v.currentTime*1000<x.gameplay_started_at)return;const regions=x.regions||[];ctx.font='13px monospace';ctx.lineWidth=1.5;let printed={};for(const r of regions){let b=r.box;if(!Array.isArray(b)||b.length!==4)continue;let [x1,y1,x2,y2]=b;if(![x1,y1,x2,y2].every(Number.isFinite)||x2<=x1||y2<=y1)continue;let cat=category(String(r.id||''));if(!enabled[cat])continue;let color=colors[cats.indexOf(cat)];ctx.strokeStyle=color;ctx.globalAlpha=r.status==='unknown'?.48:.9;ctx.strokeRect(x1,y1,x2-x1,y2-y1);let key=cat;if((printed[key]||0)<12){let value=(r.candidate_champion_name||r.candidate_item_name||r.value)??r.label;let label=String(r.id||'')+(typeof value==='string'||typeof value==='number'?' '+String(value).slice(0,25)+(r.candidate_champion_name||r.candidate_item_name?'?':''):'');ctx.fillStyle=color;ctx.fillText(label,x1,Math.max(14,y1-2));printed[key]=(printed[key]||0)+1}}
 const map=x.streams?.hub?.snapshot?.spatial_map;if(map){for(const [key,cat] of [['own_cells','Tabuleiro'],['enemy_cells','Tabuleiro'],['own_bench','Banco'],['enemy_bench','Banco']]){if(!enabled[cat])continue;let enemy=key.startsWith('enemy'),color=enemy?'#ff6868':colors[cats.indexOf(cat)];ctx.strokeStyle=color;ctx.fillStyle=color;ctx.globalAlpha=enemy?.9:.8;for(const cell of (map[key]||[])){let p=cell.center;if(!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite))continue;let [cx,cy]=p;ctx.beginPath();if(key.includes('bench'))ctx.rect(cx-22,cy-13,44,26);else for(let j=0;j<=6;j++){let angle=Math.PI*j/3;let xx=cx+20*Math.cos(angle),yy=cy+16*Math.sin(angle);if(j===0)ctx.moveTo(xx,yy);else ctx.lineTo(xx,yy)}ctx.stroke();ctx.fillText((enemy?'E':'')+cell.id,cx-12,cy-21)}}}ctx.globalAlpha=1}
function pill(text){let a=document.createElement('span');a.className='pill';a.textContent=text;return a}
function showNames(streams){
 const found=[],seen=new Set(),add=(kind,name,origin,status)=>{
  if(typeof name!=='string'||!name.trim())return;
  const key=[kind,name,origin].join('|');if(seen.has(key))return;seen.add(key);
  found.push(pill(kind+': '+name+' · '+origin+' · '+status))};
 const answer=streams.reader?.answer||{},snapshot=streams.hub?.snapshot||{};
 for(const slot of answer.shop?.slots||[])add('Herói',slot.observed_name,
   'loja '+(Number(slot.slot)+1),'nome lido');
 const selected=streams.selection;
 if(selected)add('Herói',selected.champion_name,'painel de seleção',
   selected.confirmed_champion_name?'confirmado':'candidato');
 for(const unit of snapshot.neural_units?.records||[])add('Herói',unit.candidate_name,
   'detecção visual','candidato');
 for(const [key,where] of [['own_cells','tabuleiro próprio'],['enemy_cells','tabuleiro inimigo'],
                           ['own_bench','banco próprio'],['enemy_bench','banco inimigo']]){
  for(const cell of snapshot.spatial_map?.[key]||[]){
   add('Herói',cell.visual_candidate?.candidate_name,where+' '+cell.id,
       cell.visual_candidate?.identity_verified?'confirmado':'candidato')
  }
 }
 for(const [key,where] of [['inventory','inventário'],['equipped','equipado']]){
  for(const item of snapshot.item_evidence?.[key]||[]){
   const owner=item.marker_id===undefined?'':(' · barra '+item.marker_id);
   add('Item',item.candidate_name,where+owner,
       item.identity_verified?'confirmado':(item.status||'candidato'))
  }
 }
 const area=document.getElementById('names');
 area.replaceChildren(...(found.length?found:[document.createTextNode('Nenhum nome captado neste quadro.')]))
}
async function update(){
 if(busy)return;
 const t=v.currentTime;
 if(Math.floor(t*2)===previous&&!v.paused)return;
 previous=Math.floor(t*2);busy=true;
 try{
  let a=await(await fetch('/api/status?t='+t.toFixed(3))).json();
  let d=a.streams,reader=d.reader,hub=d.hub;
  let analyzed=a.processed_until/1000;
  if(t>analyzed+1.5&&!v.paused){autoWaiting=true;v.pause()}
  if(autoWaiting&&analyzed>=t+1){autoWaiting=false;v.play().catch(()=>{})}
  document.getElementById('clock').textContent=fmt(t)+' / '+fmt(v.duration||2220);
  document.getElementById('progress').textContent='Análise até '+fmt(analyzed)+
    (autoWaiting?' · aguardando Motor 1 neste ponto':reader?' · quadro '+fmt(reader.source_ms/1000):' · sem quadro próximo');
  let ing=reader?.answer?.motor1_ingest;
  document.getElementById('receipt').textContent='Motor 2: '+
    (ing?.reader_received&&ing?.hub_received?'leitor + HUB recebidos':'entrada incompleta');
  document.getElementById('receipt').className='pill '+(ing?.reader_received&&ing?.hub_received?'':'warn');
  let hud=reader?.answer?.hud||[],summary=document.getElementById('summary');
  summary.replaceChildren(...hud.filter(x=>['stage','gold','level','xp'].includes(x.field))
    .map(x=>pill(x.field+': '+(x.value??'?'))));
  let hp=reader?.answer?.hp;if(hp)summary.append(pill('HP: '+(hp.signed_hp??'?')));
  let shop=reader?.answer?.shop?.slots||[];
  summary.append(pill('Loja: '+shop.map(x=>x.observed_name||'?').join(' · ')));
  summary.append(pill('Barras: '+(hub?.snapshot?.observed_markers?.length??'?')));
  const itemEvidence=hub?.snapshot?.item_evidence;
  summary.append(pill('Itens candidatos: '+(itemEvidence?
    ((itemEvidence.inventory||[]).length+(itemEvidence.equipped||[]).length):'?')));
  let map=hub?.snapshot?.spatial_map;
  if(map){
   summary.append(pill('Mapa próprio: '+(map.own_cells||[]).filter(c=>Array.isArray(c.center)).length+
    '/28 casas · reserva '+(map.own_bench||[]).filter(c=>Array.isArray(c.center)).length+'/9 · '+map.own_geometry_status));
   summary.append(pill('Mapa inimigo: '+(map.enemy_cells||[]).filter(c=>Array.isArray(c.center)).length+
    '/28 casas · reserva '+(map.enemy_bench||[]).filter(c=>Array.isArray(c.center)).length+'/9 · '+map.enemy_geometry_status));
  }
  let lanes=document.getElementById('lanes');
  lanes.replaceChildren(...Object.entries(a.counts).map(([key,n])=>pill((laneLabels[key]||key)+': '+n)));
  document.getElementById('notices').textContent=reader?.answer?.player_policy_feed_error?
    'Política: '+reader.answer.player_policy_feed_error:'';
  showNames(d);
  let raw=document.getElementById('raw');raw.replaceChildren();
  for(const [key,obj] of Object.entries(d)){
   let box=document.createElement('details'),s=document.createElement('summary');
   s.textContent=(laneLabels[key]||key)+' · '+(obj?fmt(obj.source_ms/1000):'sem leitura neste momento');
   let pre=document.createElement('pre');
   box.addEventListener('toggle',()=>{if(box.open)pre.textContent=obj?JSON.stringify(obj,null,2):'Sem observação sincronizada'});
   box.append(s,pre);raw.append(box)
  }
  document.getElementById('learning').textContent='Ações revisadas até aqui: '+a.reviewed_so_far+
    ' / '+a.reviewed_total+'. Decisões aprendidas e justificadas: 0 validadas.';
  paint(a);
 }catch(e){document.getElementById('notices').textContent='Erro de leitura: '+e.message}
 finally{busy=false}
}
v.addEventListener('timeupdate',update);v.addEventListener('seeked',()=>{previous=-1;update()});setInterval(update,1000);update();
</script></html>"""


class LogStudy:
    def __init__(self, video: Path, ledger: Path, output: Path, logs: Path):
        self.video, self.output, self.logs = video, output, logs
        self.actions = reviewed_actions(ledger)
        self.stop = Event()
        self.lock = Lock()
        # Index byte positions, not decoded snapshots: a full 37-minute match
        # must remain seekable without retaining hundreds of MiB in RAM.
        self.index = {key: [] for key in STREAMS}
        self.offsets = {key: 0 for key in STREAMS}
        self.gameplay_started_at = None

    def request(self, seconds: float) -> None:
        return None

    def _refresh(self) -> None:
        for key, filename in STREAMS.items():
            path = self.logs / (filename + ".jsonl")
            if not path.is_file():
                continue
            with path.open("rb") as source:
                source.seek(self.offsets[key])
                while True:
                    start = source.tell()
                    line = source.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        source.seek(start)
                        break
                    try:
                        row = json.loads(line)
                        at = row.get("source_ms")
                        if type(at) in (int, float):
                            if key == "reader" and self.gameplay_started_at is None:
                                for hud in (row.get("answer") or {}).get("hud") or []:
                                    value = hud.get("value")
                                    if hud.get("field") == "stage" and isinstance(value, str) \
                                            and len(value) == 3 and value[1] == "-" \
                                            and value[0].isdigit() and value[2].isdigit():
                                        self.gameplay_started_at = float(at)
                                        break
                            entry = (float(at), start)
                            if self.index[key] and entry < self.index[key][-1]:
                                insort(self.index[key], entry)
                            else:
                                self.index[key].append(entry)
                    except (ValueError, UnicodeDecodeError):
                        source.seek(start)
                        break
                self.offsets[key] = source.tell()

    def status(self, seconds: float) -> dict:
        with self.lock:
            self._refresh()
            ms = seconds * 1000
            selected = {}
            counts = {}
            for key, entries in self.index.items():
                counts[key] = len(entries)
                position = bisect_right(entries, (ms, float("inf"))) - 1
                if position < 0 or ms - entries[position][0] > 2000:
                    selected[key] = None
                    continue
                path = self.logs / (STREAMS[key] + ".jsonl")
                with path.open("rb") as source:
                    source.seek(entries[position][1])
                    selected[key] = json.loads(source.readline())
            regions = []
            for row in selected.values():
                if row:
                    regions.extend(row.get("regions") or [])
            processed = max((entries[-1][0] for entries in self.index.values()
                             if entries), default=0)
            return {"streams": selected, "regions": regions, "counts": counts,
                    "processed_until": processed,
                    "gameplay_started_at": self.gameplay_started_at,
                    "reviewed_total": len(self.actions),
                    "reviewed_so_far": sum(a["time_ms"] <= ms for a in self.actions)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    watch_one_match.HTML = HTML
    serve(LogStudy(args.video, args.ledger, args.logs, args.logs), "127.0.0.1", args.port)


if __name__ == "__main__":
    main()
