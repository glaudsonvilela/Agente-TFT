"""Mapping-first session: independent neural/native consumers and natural-frame collection."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json, queue, threading, time, uuid
from .core import Registry, Observer, native_regions, sha, dump
from .dataset import Latest, Store

def stats(values):
    import numpy as np
    if not values:return dict(n=0,p50_ms=None,p95_ms=None)
    return dict(n=len(values),p50_ms=float(np.quantile(values,.5)),p95_ms=float(np.quantile(values,.95)),max_ms=max(values))

@dataclass
class Options:
    video: str
    output: str
    model: str
    worker: str
    configs: str
    ffmpeg: str='ffmpeg'
    ffprobe: str='ffprobe'
    tesseract: str='tesseract'
    controls: str|None=None
    board_reference: str|None=None
    seconds: float=300
    map_hz: float=4
    reader_hz: float=1
    sample_hz: float=1
    max_samples: int=600
    max_bytes: int=1024**3
    scenario: str='natural-replay'
    dataset_only: bool=False
    capture_consent: bool=False
    capture_expected: dict|None=None
    def validate(self):
        if not self.model:raise ValueError('Selecione o modelo espacial L2/L3 (deployment-candidate.json).')
        if not 1<=self.seconds<=7200 or not .2<=self.map_hz<=15 or not .1<=self.reader_hz<=5 or not .1<=self.sample_hz<=2:
            raise ValueError('Duração/frequência fora dos limites.')
        if not self.scenario.strip() or len(self.scenario)>100:raise ValueError('Nome do cenário inválido.')
        for p in (self.model,self.worker):
            if not Path(p).is_file():raise ValueError('Arquivo não encontrado: '+str(p))

class Session:
    def __init__(self, options):
        options.validate();self.options=options
        self.id=uuid.uuid4().hex;self.cancel=threading.Event();self.producer_done=threading.Event();self.done=threading.Event()
        self.map_pending=Latest();self.native_pending=Latest();self.preview=Latest();self.map_results=Latest();self.native_results=Latest()
        self.counts=Counter();self.coverage=Counter();self.traces=[];self.lock=threading.Lock()
        self.store=Store(options.output,options.max_samples,options.max_bytes)
        self.source=self.worker=self.hp_worker=self.model=None;self.error=None;self.phase='preflight';self.finished=False
        self.source_info={};self.versions={};self.source_hash=None;self.registry=None
        self.started=time.perf_counter_ns();self.thread=threading.Thread(target=self._run,daemon=True)
    def start(self):self.thread.start();return self
    def stop(self):
        self.cancel.set()
        def close():
            for obj in (self.source,self.worker,self.hp_worker):
                if obj:
                    try:obj.close()
                    except Exception:pass
        threading.Thread(target=close,daemon=True).start()
    def _run(self):
        threads=[]
        try:
            from e1.protocol import NativeWorker
            from .input_source import InputPlan
            o=self.options
            self.phase='Verificando a fonte selecionada…'
            input_plan=InputPlan(o,self.id)
            self.source_info=input_plan.info
            self.source_hash=self.source_info.get('sha256')
            self.registry=Registry(o.configs,o.controls)
            self.model=Observer(o.model)
            self.versions=dict(model_sha256=self.model.hash,model_load_ms=self.model.load_ms,
                               configs=self.registry.hashes,native_binary_sha256=sha(o.worker),
                               hud='numeric_gray_v3',controls='explicit_S4_or_custom' if o.controls else 'S3_frozen',
                               hp='HP1_baseline_diagnostic',board='B1_optional',
                               trained_regions=['bench','shop'],other_HUD_regions='registered_readers_not_neural_classes')
            self.worker=NativeWorker(o.worker,o.configs,o.tesseract,o.controls,Path(o.output)/'native-stderr.log')
            hp_binary=Path(o.worker).with_name('agente-tft-hm-hp'+('.exe' if __import__('os').name=='nt' else ''))
            if not hp_binary.is_file():
                hp_binary=Path(o.configs).parent/'tools/hm-hp-native/target/release'/hp_binary.name
            self.hp_worker=NativeWorker(str(hp_binary),o.configs,o.tesseract,log=Path(o.output)/'hp-stderr.log')
            self.versions['hp_binary_sha256']=sha(hp_binary)
            if not self.worker.ready.get('ocr_available') or not self.hp_worker.ready.get('ocr_available'):raise ValueError('Tesseract indisponível; não simular leituras.')
            if o.board_reference:
                from PIL import Image
                with Image.open(o.board_reference) as im:
                    im=im.convert('RGB');w,h=im.size;b=im.tobytes()
                self.worker.request(dict(op='reference',id=0,source_ms=0,width=w,height=h,bytes=len(b)),b)
                self.versions['board_reference_sha256']=sha(o.board_reference)
            self.source=input_plan.start()
            for target in (self._map_loop,self._native_loop):
                t=threading.Thread(target=target,daemon=True);t.start();threads.append(t)
            self.phase='Mapeando HUD / coletando pixels naturais'
            next_map=next_native=next_sample=-1
            neutral_interval=max(1/o.sample_hz,o.seconds/max(1,o.max_samples//2))
            for f in self.source.frames(self.cancel,o.seconds):
                if self.cancel.is_set():break
                if self.store.error:raise OSError(self.store.error)
                self.counts['source_frames']+=1;self.preview.put(f)
                self.store.emit('telemetry',dict(event='source',frame_id=f.id,source_ms=f.pts_ms,
                   due_ns=f.due_ns,ready_ns=f.ready_ns,source_late_ms=(f.ready_ns-f.due_ns)/1e6,
                   geometry_segment=f.epoch,capture=getattr(f,'capture',None)))
                if f.due_ns>=next_sample:
                    next_sample=f.due_ns+int(1e9*neutral_interval)
                    # Neutral periodic selection independent of model confidence.
                    self.store.emit('periodic',dict(frame_id=f.id,source_ms=f.pts_ms,reason='periodic_neutral'),f,True)
                if f.due_ns>=next_map:
                    next_map=f.due_ns+int(1e9/o.map_hz);self.map_pending.put(f);self.counts['mapper_submitted']+=1
                if f.due_ns>=next_native:
                    next_native=f.due_ns+int(1e9/o.reader_hz);self.native_pending.put(f);self.counts['native_submitted']+=1
            self.producer_done.set()
            for t in threads:t.join(30)
            if any(t.is_alive() for t in threads):raise TimeoutError('Trabalhador não encerrou dentro do prazo')
            self.model.verify()
            input_plan.verify(self.cancel.is_set())
        except Exception as exc:
            self.error=str(exc);self.stop()
        finally:
            self.producer_done.set()
            for obj in (self.source,self.worker,self.hp_worker):
                if obj:
                    try:obj.close()
                    except Exception as exc:self.error=self.error or str(exc)
            for t in threads:t.join(3)
            if any(t.is_alive() for t in threads):self.error=self.error or 'Trabalhador ainda ativo; saída parcial'
            self.done.set();self.phase='Concluindo pacote de HUD'
    def _map_loop(self):
        next_save=-1
        interval=max(2000,self.options.seconds*1000/max(1,self.options.max_samples//4))
        try:
            while not self.cancel.is_set():
                try:f=self.map_pending.get()
                except queue.Empty:
                    if self.producer_done.is_set():break
                    continue
                start=time.perf_counter_ns();obs=self.model.observe(f);end=time.perf_counter_ns()
                r=dict(frame_id=f.id,source_ms=f.pts_ms,regions=obs['regions'],neural=obs,
                       queue_ms=(start-f.ready_ns)/1e6,source_to_map_ms=(end-f.due_ns)/1e6,
                       image_size=[f.width,f.height],ground_truth=False,
                       model_trained=False,profile_promoted=False)
                with self.lock:
                    for reg in r['regions']:self.coverage[(reg['id'],reg['status'])]+=1
                    self.traces.append(dict(kind='map',frame_id=f.id,source_due_ns=f.due_ns,
                           ready_ns=end,queue_ms=r['queue_ms'],total_ms=r['source_to_map_ms'],
                           inference_ms=obs['inference_ms'],resize_ms=obs['resize_ms']))
                take=f.pts_ms>=next_save
                if take:next_save=f.pts_ms+interval
                self.store.emit('mapping-events',r,f,take)
                self.map_results.put(dict(frame=f,record=r,ready_ns=end));self.counts['mapped_frames']+=1
        except Exception as exc:self.error=str(exc);self.stop()
    def _native_loop(self):
        next_save=-1
        interval=max(2000,self.options.seconds*1000/max(1,self.options.max_samples//4))
        try:
            while not self.cancel.is_set():
                try:f=self.native_pending.get()
                except queue.Empty:
                    if self.producer_done.is_set():break
                    continue
                start=time.perf_counter_ns()
                answer=self.worker.request(dict(op='frame',id=f.id,source_ms=round(f.pts_ms),
                              width=f.width,height=f.height,bytes=len(f.rgb)),f.rgb,timeout=12)
                hp_start=time.perf_counter_ns()
                hp=self.hp_worker.request(dict(op='frame',id=f.id,source_ms=round(f.pts_ms),width=f.width,height=f.height,bytes=len(f.rgb)),f.rgb,timeout=12)
                answer['hp']=hp['hp']
                answer['spans'].append(dict(stage='hp_baseline',start_ms=(hp_start-start)/1e6,duration_ms=hp['native_ms']))
                if answer.get('id')!=f.id:raise ValueError('Resposta pertence a outro frame')
                end=time.perf_counter_ns();regions=native_regions(answer,self.registry,f.width,f.height)
                r=dict(frame_id=f.id,source_ms=f.pts_ms,regions=regions,answer=answer,
                       queue_ms=(start-f.ready_ns)/1e6,source_to_reader_ms=(end-f.due_ns)/1e6,
                       native_roundtrip_ms=(end-start)/1e6,image_size=[f.width,f.height],ground_truth=False)
                with self.lock:
                    for reg in regions:self.coverage[(reg['id'],reg['status'])]+=1
                    self.traces.append(dict(kind='reader',frame_id=f.id,source_due_ns=f.due_ns,
                      ready_ns=end,queue_ms=r['queue_ms'],total_ms=r['source_to_reader_ms'],
                      native_roundtrip_ms=r['native_roundtrip_ms'],spans=answer.get('spans',[])))
                take=f.pts_ms>=next_save
                if take:next_save=f.pts_ms+interval
                self.store.emit('roi-observations',r,f,take)
                self.native_results.put(dict(frame=f,record=r,ready_ns=end));self.counts['read_frames']+=1
        except Exception as exc:self.error=str(exc);self.stop()
    def acknowledge(self,item,kind):
        f=item['frame'];at=time.perf_counter_ns()
        self.store.emit('telemetry',dict(event='ui_applied',kind=kind,frame_id=f.id,
             source_age_ms=(at-f.due_ns)/1e6,ui_queue_ms=(at-item['ready_ns'])/1e6,
             physical_display_measured=False))
        self.counts['ui_'+kind]+=1
    def finish(self):
        if not self.done.is_set():raise RuntimeError('Sessão ainda executando')
        if self.finished:raise RuntimeError('Sessão já selada')
        self.finished=True
        with self.lock:traces=list(self.traces);cov=list(self.coverage.items())
        mapping=[x for x in traces if x['kind']=='map'];reading=[x for x in traces if x['kind']=='reader']
        stages={}
        for x in reading:
            for s in x.get('spans',[]):stages.setdefault(s['stage'],[]).append(s['duration_ms'])
        result=dict(schema_version=1,policy='hud_mapper_hm2' if self.source_info.get('source_kind')=='native_capture' else 'hud_mapper_hm1',primary_objective='HUD_mapping_and_natural_training_material',
           session_id=self.id,source=self.source_info,versions=self.versions,
           execution_complete=self.error is None and not self.cancel.is_set(),error=self.error,
           cancelled=self.cancel.is_set(),counts=dict(self.counts),
           queues=dict(mapper_replaced=self.map_pending.replaced,native_replaced=self.native_pending.replaced,
                       preview_replaced=self.preview.replaced,map_ui_replaced=self.map_results.replaced,
                       reader_ui_replaced=self.native_results.replaced),
           coverage=[dict(region=k[0],status=k[1],frames=v) for k,v in sorted(cov)],
           timings=dict(map_source_to_result=stats([x['total_ms'] for x in mapping]),
                        map_inference=stats([x['inference_ms'] for x in mapping]),
                        map_resize=stats([x['resize_ms'] for x in mapping]),
                        mapper_queue=stats([x['queue_ms'] for x in mapping]),
                        readers_source_to_result=stats([x['total_ms'] for x in reading]),
                        readers_queue=stats([x['queue_ms'] for x in reading]),
                        stages={k:stats(v) for k,v in stages.items()}),
           observations_are_ground_truth=False,neural_scope=['bench','shop'],
           full_hud_neural_mapping=False,board_cells_validated=False,model_trained=False,torch_loaded_in_mapper='torch' in __import__('sys').modules,
           profile_promoted=False,game_state_updated=False,continuous_learning_connected=False,
           official_game_connected=False,physical_display_measured=False,
           screen_capture_active=self.source_info.get('source_kind')=='native_capture',
           capture_is_not_game_memory_access=True,live_strategy_enabled=False,
           next_step='inspect saved native pixels and observation provenance; train only explicit supervision',
           elapsed_seconds=(time.perf_counter_ns()-self.started)/1e9)
        return self.store.close(result)
