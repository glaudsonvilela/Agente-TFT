"""HM3 runtime session: HUD-first capture with bounded exact-pixel reader reuse."""
from __future__ import annotations
import copy, hashlib, queue, time
from .core import native_regions, crop_box
from .session import Session

READER_CACHE_MAX_MS = 750.0

def _group_boxes(registry, width, height):
    if (width, height) != (1920, 1080):
        return []
    rows = registry.fixed(width, height)
    hud = [r["box"] for r in rows if r.get("box") and str(r["id"]).startswith("hud.")]
    shop = [r["box"] for r in rows if r.get("box") and (str(r["id"]).startswith("shop.") or str(r["id"]).startswith("control."))]
    def union(boxes):
        if not boxes:return None
        return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    # Player list strip is deliberately broad because HP moves vertically.
    return [b for b in (union(hud), union(shop), [1640,120,1919,920]) if b]

def reader_signature(frame, registry):
    """Exact RGB hash over reader-relevant pixels. No fuzzy threshold can hide change."""
    boxes=_group_boxes(registry,frame.width,frame.height)
    if not boxes:return None
    h=hashlib.blake2s(digest_size=16)
    view=memoryview(frame.rgb);stride=frame.width*3
    for box in boxes:
        x1,y1,x2,y2=crop_box(box,frame.width,frame.height)
        h.update(bytes((x1&255,y1&255,x2&255,y2&255)))
        start=x1*3;end=x2*3
        for y in range(y1,y2):
            row=y*stride
            h.update(view[row+start:row+end])
    return h.digest()

class RuntimeSession(Session):
    """Same neural/data pipeline, with reader work gated only by exact-pixel equality."""
    def __init__(self, options):
        super().__init__(options)
        self._last_native=None

    def _native_loop(self):
        next_save=-1
        interval=max(2000,self.options.seconds*1000/max(1,self.options.max_samples//4))
        try:
            while not self.cancel.is_set():
                try:f=self.native_pending.get()
                except queue.Empty:
                    if self.producer_done.is_set():break
                    continue
                started=time.perf_counter_ns()
                sig_started=started
                signature=None if self.options.board_reference else reader_signature(f,self.registry)
                signature_ms=(time.perf_counter_ns()-sig_started)/1e6
                cached=False;native_executed=False;answer=None;regions=None
                if (f.width,f.height)!=(1920,1080):
                    self.counts["reader_resolution_skipped"]+=1
                    regions=self.registry.fixed(f.width,f.height)
                    answer=dict(id=f.id,origin="resolution_gate",spans=[],hud=[],shop=None,controls=None,hp=None)
                elif (signature is not None and self._last_native and
                      self._last_native["signature"]==signature and self._last_native["epoch"]==f.epoch and
                      (f.due_ns-self._last_native["due_ns"])/1e6<=READER_CACHE_MAX_MS):
                    cached=True;self.counts["reader_exact_cache_hits"]+=1
                    regions=copy.deepcopy(self._last_native["regions"])
                    for r in regions:
                        r["cached_from_frame_id"]=self._last_native["frame_id"]
                        r["cache_age_ms"]=(f.due_ns-self._last_native["due_ns"])/1e6
                    answer=copy.deepcopy(self._last_native["answer"])
                    answer["id"]=f.id;answer["source_ms"]=round(f.pts_ms)
                    answer["origin"]="exact_reader_pixel_cache"
                    answer["reused_from_frame_id"]=self._last_native["frame_id"]
                    answer["spans"]=[dict(stage="reader_exact_cache",start_ms=0.0,duration_ms=signature_ms)]
                else:
                    native_executed=True;self.counts["reader_native_runs"]+=1
                    answer=self.worker.request(dict(op="frame",id=f.id,source_ms=round(f.pts_ms),
                                  width=f.width,height=f.height,bytes=len(f.rgb)),f.rgb,timeout=12)
                    hp_start=time.perf_counter_ns()
                    hp=self.hp_worker.request(dict(op="frame",id=f.id,source_ms=round(f.pts_ms),
                                  width=f.width,height=f.height,bytes=len(f.rgb)),f.rgb,timeout=12)
                    answer["hp"]=hp["hp"]
                    answer["spans"].append(dict(stage="hp_baseline",start_ms=(hp_start-started)/1e6,duration_ms=hp["native_ms"]))
                    if answer.get("id")!=f.id:raise ValueError("Resposta pertence a outro frame")
                    regions=native_regions(answer,self.registry,f.width,f.height)
                    if signature is not None:
                        self._last_native=dict(signature=signature,epoch=f.epoch,due_ns=f.due_ns,frame_id=f.id,
                                               answer=copy.deepcopy(answer),regions=copy.deepcopy(regions))
                ended=time.perf_counter_ns()
                r=dict(frame_id=f.id,source_ms=f.pts_ms,regions=regions,answer=answer,
                       queue_ms=(started-f.ready_ns)/1e6,source_to_reader_ms=(ended-f.due_ns)/1e6,
                       reader_elapsed_ms=(ended-started)/1e6,reader_signature_ms=signature_ms,
                       reader_cache_exact_hit=cached,native_executed=native_executed,
                       image_size=[f.width,f.height],ground_truth=False)
                with self.lock:
                    for reg in regions:self.coverage[(reg["id"],reg["status"])]+=1
                    self.traces.append(dict(kind="reader",frame_id=f.id,source_due_ns=f.due_ns,
                      ready_ns=ended,queue_ms=r["queue_ms"],total_ms=r["source_to_reader_ms"],
                      reader_elapsed_ms=r["reader_elapsed_ms"],signature_ms=signature_ms,
                      cache_exact_hit=cached,native_executed=native_executed,spans=answer.get("spans",[])))
                take=f.pts_ms>=next_save
                if take:next_save=f.pts_ms+interval
                self.store.emit("roi-observations",r,f,take)
                self.native_results.put(dict(frame=f,record=r,ready_ns=ended));self.counts["read_frames"]+=1
        except Exception as exc:
            self.error=str(exc);self.stop()
