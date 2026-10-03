"""Bounded asynchronous natural-pixel collection. Labels and observations remain separate."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import hashlib, io, json, os, queue, shutil, threading, time
from PIL import Image
from .core import dump, sha, crop_box, valid_box, ENVELOPES, xyxy

class Latest:
    """Single replaceable pending item; discarded events are explicitly counted."""
    def __init__(self):
        self.q=queue.Queue(maxsize=1);self.lock=threading.Lock();self.replaced=0
    def put(self, value):
        with self.lock:
            try:self.q.get_nowait();self.replaced+=1
            except queue.Empty:pass
            self.q.put_nowait(value)
    def get(self, timeout=.05):return self.q.get(timeout=timeout)
    def empty(self):return self.q.empty()

class Store:
    def __init__(self, root, max_samples=600, max_bytes=1024**3, reserve_bytes=512*1024**2):
        self.root=Path(root)
        if self.root.exists() or self.root.is_symlink():raise ValueError('Pasta de sessão já existe')
        if not 1<=max_samples<=3600 or not 1024**2<=max_bytes<=16*1024**3:
            raise ValueError('Orçamento de coleta inválido')
        self.root.mkdir(parents=True,exist_ok=False)
        (self.root/'samples').mkdir();(self.root/'crops').mkdir()
        self.max_samples=max_samples;self.max_bytes=max_bytes;self.reserve=reserve_bytes
        self.jobs=queue.Queue(maxsize=8);self.done=threading.Event();self.error=None
        self.counts=Counter();self.records=[];self.events=[];self.bytes=0
        self.log_bytes=0
        self.closed=False;self.hashes={};self.previous={};self.seen={};self.io_ms=[]
        self.thread=threading.Thread(target=self._writer,daemon=True);self.thread.start()
    def emit(self, stream, data, frame=None, sample=False):
        # Snapshot JSON before handing it to the writer. Frame.rgb is immutable bytes.
        snapshot=json.loads(json.dumps(data,ensure_ascii=False,allow_nan=False))
        try:self.jobs.put_nowait((stream,snapshot,frame,sample))
        except queue.Full:self.counts['write_queue_dropped']+=1;return False
        return True
    def _writer(self):
        files={}
        try:
            while not self.done.is_set() or not self.jobs.empty():
                try:stream,data,frame,sample=self.jobs.get(timeout=.1)
                except queue.Empty:continue
                started=time.perf_counter_ns()
                if stream not in ('mapping-events','roi-observations','board-hub-observations','replay-tips','telemetry','periodic'):
                    raise ValueError('Fluxo não registrado')
                if stream not in files:files[stream]=(self.root/(stream+'.jsonl')).open('x',encoding='utf-8')
                line=json.dumps(data,ensure_ascii=False,allow_nan=False)+'\n'
                self.log_bytes+=len(line.encode('utf-8'))
                if self.log_bytes>128*1024**2 or shutil.disk_usage(self.root).free<self.reserve:
                    raise OSError('Orçamento de telemetria/disco atingido; sessão parcial preservada')
                files[stream].write(line);files[stream].flush()
                if sample and frame:self._save(frame,data,stream)
                self.counts[stream+'_events']+=1;self.io_ms.append((time.perf_counter_ns()-started)/1e6)
        except Exception as e:
            self.error=str(e)
        finally:
            for f in files.values():f.close()
    def _save(self, frame, data, stream):
        key=str(frame.id)
        if key in self.seen:
            row=self.seen[key];row['event_streams'].append(stream)
            if stream=='roi-observations':
                row['roi_event_available']=True
                self._crops(Image.frombytes('RGB',(frame.width,frame.height),frame.rgb),row,data,frame)
            return
        if len(self.records)>=self.max_samples:
            self.counts['sample_limit_skipped']+=1;return
        if shutil.disk_usage(self.root).free<self.reserve:
            self.counts['disk_reserve_skipped']+=1;return
        h=hashlib.sha256(frame.rgb).hexdigest()
        im=Image.frombytes('RGB',(frame.width,frame.height),frame.rgb)
        small=im.resize((80,45),Image.Resampling.BILINEAR).tobytes()
        prev=self.previous.get('global'); self.previous['global']=small
        change=None if prev is None else sum(abs(a-b) for a,b in zip(small,prev))/len(small)
        flags=['periodic_neutral'] if stream=='periodic' else ['reader_evidence']
        if change is not None and change>8:flags.append('visual_change_candidate')
        if any(r.get('status')=='unknown' for r in data.get('regions',[])):flags.append('uncertain_proposal')
        # No "occluded" label inferred merely from missing text or neural abstention.
        buffer=io.BytesIO();im.save(buffer,format='PNG',compress_level=1);png=buffer.getvalue()
        if self.bytes+len(png)>self.max_bytes:
            self.counts['byte_limit_skipped']+=1;return
        name=f'samples/{frame.id:09d}.png';p=self.root/name
        with p.open('xb') as f:f.write(png)
        self.bytes+=len(png)
        row=dict(sample_id=key,frame_id=frame.id,source_ms=frame.pts_ms,width=frame.width,height=frame.height,
                 image=name,image_sha256=hashlib.sha256(png).hexdigest(),decoded_rgb_sha256=h,
                 pixel_format='rgb24',coordinate_space='source_pixel_edges',event_streams=[stream],
                 geometry_segment=getattr(frame,'epoch',0),capture=getattr(frame,'capture',None),
                 sampling_reasons=flags,visual_change_mae=change,targets=None,
                 neural_predictions_are_labels=False,supervision='unlabelled_natural_frame',crops=[])
        self._crops(im,row,data,frame)
        self.records.append(row);self.seen[key]=row
        for flag in flags:self.counts['sample_'+flag]+=1
        self.counts['samples_saved']=len(self.records)
    def _crops(self,im,row,data,frame):
        for r in data.get('regions',[]):
            if any(c['id']==r['id'] for c in row['crops']):continue
            b=r.get('box')
            if not b or not valid_box(b,frame.width,frame.height):continue
            # Native registered ROIs only; unknown neural proposals stay on the full frame.
            if str(r['id']).startswith('neural.'):continue
            coords=crop_box(b,frame.width,frame.height)
            if (coords[2]-coords[0])*(coords[3]-coords[1])>300000:continue
            cb=io.BytesIO();im.crop(coords).save(cb,format='PNG',compress_level=1);content=cb.getvalue()
            if self.bytes+len(content)>self.max_bytes:break
            rid=''.join(x if x.isalnum() or x in '._-' else '_' for x in str(r['id']))
            cn=f'crops/{frame.id:09d}-{rid}.png'
            with (self.root/cn).open('xb') as f:f.write(content)
            self.bytes+=len(content)
            row['crops'].append(dict(id=r['id'],image=cn,sha256=hashlib.sha256(content).hexdigest(),box=list(coords),
                                     observed_status=r.get('status'),crop_is_truth=False))
    def close(self, session):
        if self.closed:raise RuntimeError('Sessão já finalizada')
        self.done.set();self.thread.join(30)
        if self.thread.is_alive():raise RuntimeError('Escrita pendente; sessão permanece parcial')
        self.closed=True
        if self.error:session['error']=self.error;session['execution_complete']=False
        session['collection']={**dict(self.counts),'png_bytes':self.bytes,'sample_budget':self.max_samples,
                               'byte_budget':self.max_bytes,'samples_saved':len(self.records)}
        manifest=dict(schema_version=1,policy='hm1_natural_mapping_dataset',session_id=session['session_id'],
                      source=session['source'],samples=self.records,reader_versions=session.get('versions'),
                      training_executed=False,ground_truth_available=False,
                      split_unit=session['source'].get('split_unit','source_video_sha256'),coordinate_space='source_pixel_edges',
                      weights_updated=False,raw_and_derived_separate=True,
                      warning='Unknown does not mean absent; temporal agreement is not correctness.')
        dump(self.root/'training-manifest.json',manifest)
        dump(self.root/'summary.json',session)
        dump(self.root/'collection-metrics.json',dict(counts=dict(self.counts),bytes=self.bytes,write_ms=self.io_ms))
        # This text includes mapping coverage first; performance is secondary.
        with (self.root/'comparison.txt').open('x',encoding='utf-8') as f:
            f.write('HUD MAPPER — MAPEAMENTO / DADOS NATURAIS\n')
            f.write(json.dumps(session,ensure_ascii=False,indent=2,allow_nan=False))
        hashes={str(p.relative_to(self.root)):sha(p) for p in self.root.rglob('*') if p.is_file()}
        dump(self.root/('COMPLETE.json' if session.get('execution_complete') else 'PARTIAL.json'),hashes)
        return session
