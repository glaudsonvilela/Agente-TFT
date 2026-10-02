"""Explicit coordinate/observation contracts. Prediction is never a training label."""
from __future__ import annotations
import hashlib, json, math, time
from pathlib import Path
import numpy as np
from PIL import Image

PANELS = ('bench', 'shop')
# Frozen development envelopes from L2. They are NOT physical frame borders.
ENVELOPES = {'bench': [358, 682, 1038, 146], 'shop': [345, 915, 1220, 160]}

def load_json(path, limit=2*1024**2):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > limit:
        raise ValueError(f'Arquivo inválido ou excede orçamento: {p}')
    return json.loads(p.read_text(encoding='utf-8-sig'))

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def dump(path, data):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)

def xyxy(rect):
    if isinstance(rect, dict):
        x,y,w,h = (float(rect[k]) for k in ('x','y','width','height'))
    else:
        x,y,w,h = map(float, rect)
    return [x,y,x+w,y+h]

def valid_box(box, width, height):
    return len(box)==4 and all(math.isfinite(float(v)) for v in box) and \
        0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height

def crop_box(box, width, height):
    """Check BEFORE rounding; do not clip or repair an invalid proposal."""
    if not valid_box(box, width, height):
        raise ValueError('Retângulo fora da imagem, invertido ou não finito')
    result = (math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3]))
    if not valid_box(result, width, height):
        raise ValueError('Retângulo inválido após conversão de bordas')
    return result

def region(region_id, box=None, status='registered_not_verified', value=None, **extra):
    return dict(id=region_id, box=box, status=status, value=value,
                coordinate_space='source_pixel_edges', ground_truth=False, **extra)

class Registry:
    """Geometry comes from the existing configs; no champions embedded in geometry."""
    def __init__(self, root, controls=None):
        root = Path(root)
        self.hud = load_json(root/'hud/tft-1920x1080-match001-v3-gray.json')
        self.shop = load_json(root/'ui/match001-desktop-1920x1080-ptbr-v1.json')
        self.control = load_json(controls or root/'ui/match001-shop-controls-v1.json')
        self.board = load_json(root/'ui/match001-board-bench-v1.json')
        self.inputs = [root/'hud/tft-1920x1080-match001-v3-gray.json',
                       root/'ui/match001-desktop-1920x1080-ptbr-v1.json',
                       Path(controls) if controls else root/'ui/match001-shop-controls-v1.json',
                       root/'ui/match001-board-bench-v1.json']
        self.hashes = {p.name: sha(p) for p in self.inputs}
    def fixed(self, width, height):
        compatible = (width,height)==(1920,1080)
        out=[]
        for r in self.hud['regions']:
            a=r['rect']; box=xyxy([a['x']*1920,a['y']*1080,a['width']*1920,a['height']*1080])
            out.append(region('hud.'+r['field'],box if compatible else None,
                              'registered_not_verified' if compatible else 'resolution_incompatible',
                              basis='frozen_numeric_gray_v3_profile'))
        for slot in self.shop['slots']:
            for field in ('card','name','cost'):
                out.append(region(f"shop.{slot['slot']}.{field}",xyxy(slot[field]) if compatible else None,
                                  'registered_not_verified' if compatible else 'resolution_incompatible',
                                  basis='frozen_shop_profile'))
        # Controls structs are inspected recursively; templates are not regions.
        for key, value in self.control.items():
            if isinstance(value, list):
                for r in value:
                    if isinstance(r,dict) and 'id' in r and 'rect' in r:
                        out.append(region('control.'+str(r['id']),xyxy(r['rect']) if compatible else None,
                                          'registered_not_verified' if compatible else 'resolution_incompatible',
                                          basis='selected_controls_profile'))
        for name in PANELS:
            out.append(region(name+'.envelope',xyxy(ENVELOPES[name]) if compatible else None,
                              'development_seed_not_verified' if compatible else 'resolution_incompatible',
                              basis='L2_development_envelope'))
        # Explicit inventory, NOT fabricated locations for unimplemented components.
        for name in ('player.hp','board.cells','units.identity','units.stars','items','augments','attributes'):
            out.append(region(name,None,'not_connected' if name=='player.hp' else 'not_established'))
        return out

def neural_regions(raw, width, height):
    a = np.asarray(raw, dtype=np.float64)
    if a.shape != (1,2,5) or not np.isfinite(a).all():
        raise ValueError('Saída neural incompatível')
    out=[]
    for name,row in zip(PANELS,a[0]):
        box=(row[:4]*[width,height,width,height]).tolist()
        geometry=(valid_box(box,width,height) and (box[2]-box[0])/width>=.08 and (box[3]-box[1])/height>=.015)
        # Visibility threshold is the frozen L2 policy, not a calibrated probability.
        visible=float(row[4])>=2.1972245773362196
        accepted=geometry and visible
        delta = None
        if (width,height)==(1920,1080):
            delta = (np.asarray(box)-xyxy(ENVELOPES[name])).tolist()
        out.append(region('neural.'+name,box,'coarse_candidate' if accepted else 'unknown',
            basis='neural_proposal_not_label', visibility_logit=float(row[4]),
            geometry_valid=geometry, visibility_pass=visible,
            map_usable_by_readers=False, delta_from_seed_px=delta,
            delta_is_error=False, unsupported_resolution=(width,height)!=(1920,1080)))
    return out

def native_regions(answer, registry, width, height):
    """Each response stays attached to its OWN pixels; no current-frame substitution."""
    rows=registry.fixed(width,height); by_id={r['id']:r for r in rows}
    for read in answer.get('hud') or []:
        r=by_id.get('hud.'+read['field'])
        if r:r.update(status=read['status'],value=read.get('value'),text=read.get('text'),confidence=read.get('confidence'))
    shop=answer.get('shop') or {}
    for slot in shop.get('slots',[]):
        i=slot.get('slot'); status=slot.get('status','unknown')
        for field in ('card','name','cost'):
            r=by_id.get(f'shop.{i}.{field}')
            if r:
                value=slot.get('observed_'+field) if field!='card' else None
                field_status=status if field=='card' or status in ('unavailable','empty_observed') else ('observed' if value is not None else 'unknown')
                r.update(status=field_status,value=value,observation=slot,confidence=slot.get(field+'_confidence'))
    control=answer.get('controls') or {}
    for group in ('controls','numbers'):
        for read in control.get(group,[]):
            rid='control.'+str(read['id']); r=by_id.get(rid)
            if r is None:
                r=region(rid,xyxy(read['rect']) if read.get('rect') else None);rows.append(r)
            r.update(status=read.get('status','unknown'),value=read.get('value',read.get('appearance')),observation=read)
    board=answer.get('board') or {}
    for slot in board.get('bench',[]):
        rows.append(region('bench.slot.'+str(slot['slot']),xyxy(slot['rect']),slot['evidence'],
                    basis='B1_reference_signal_not_occupancy',occupancy=None,observation=slot))
    for marker in board.get('markers',[]):
        if marker.get('rect'):
            rows.append(region('board.marker.'+str(marker['id']),xyxy(marker['rect']),'bar_candidate',
                        basis='B1_bar_not_unit',occupancy=None))
    if board:
        by_id['board.cells'].update(status='projection_proposals_not_validated',observation=board,
            guide_points=board.get('board',[]) if board.get('projection_status')=='reference_arena_match' else [],
            guide_points_are_observed=False)
    hp=answer.get('hp')
    if isinstance(hp,dict):
        loc=(hp.get('location') or {}).get('candidates',[])
        r=by_id['player.hp'];r.update(status=hp.get('status','unknown'),value=hp.get('signed_hp'),observation=hp,
          box=xyxy(loc[0]['hp_rect']) if len(loc)==1 else None, identity_verified=False)
    return rows

class Observer:
    """Use the existing small L2/L3 ONNX, with its semantic coordinate contract checked."""
    def __init__(self, metadata):
        from e1.model import MapObserver
        p=Path(metadata).resolve(strict=True);m=load_json(p,65536)
        if m.get('coordinate_format')!='normalized_tlbr' or m.get('panels')!=list(PANELS) or m.get('schema_version')!=2:
            raise ValueError('Use a exportação espacial L2/L3, não L1/U1 ou modelo genérico.')
        mp=p.parent/'candidate-model.onnx'
        if mp.is_symlink() or not mp.is_file() or mp.stat().st_size>8*1024**2:
            raise ValueError('ONNX inválido ou excede 8 MiB')
        # Reject ONNX external tensors; the selected file must be self-contained.
        import onnx
        proto=onnx.load_model_from_string((p.parent/'candidate-model.onnx').read_bytes())
        def check_graph(g):
            for t in g.initializer:
                if t.external_data or t.data_location==onnx.TensorProto.EXTERNAL:
                    raise ValueError('ONNX externo não permitido')
            for node in g.node:
                for attr in node.attribute:
                    if attr.type==onnx.AttributeProto.GRAPH:check_graph(attr.g)
                    if attr.type==onnx.AttributeProto.GRAPHS:
                        for sub in attr.graphs:check_graph(sub)
        check_graph(proto.graph)
        self.inner=MapObserver(p);self.hash=self.inner.hash;self.load_ms=self.inner.load_ms
        self.path=p;self.meta_hash=sha(p)
    def observe(self, frame):
        result=self.inner.observe(frame)
        result['regions']=neural_regions(result['raw'],frame.width,frame.height)
        result['model_scope']=['bench_envelope','shop_envelope']
        return result
    def verify(self):
        if sha(self.path)!=self.meta_hash or sha(self.path.parent/'candidate-model.onnx')!=self.hash:
            raise ValueError('Modelo alterado durante a sessão')
