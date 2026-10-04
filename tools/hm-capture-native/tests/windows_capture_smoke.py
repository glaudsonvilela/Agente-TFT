"""Real WGC/D3D11 capture of an owned test window and one available monitor.
No TFT, game process, trained model, or anti-cheat is accessed by this test.
"""
import argparse, json, os, queue, struct, subprocess, threading, time
from pathlib import Path
import tkinter as tk


def exact(stream, count):
    out=bytearray()
    while len(out)<count:
        block=stream.read(count-len(out))
        if not block:raise EOFError('Truncated capture packet')
        out.extend(block)
    return bytes(out)


def exercise(binary, target, root, canvas, resize=False):
    proc=subprocess.Popen([str(binary),'stream','--kind',target['kind'],'--id',target['id'],
          '--seconds','3','--hz','4','--preview-hz','12','--consent'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    events=queue.Queue();records=[];failures=[];done=threading.Event()
    def read():
        try:
            while True:
                length=struct.unpack('<I',exact(proc.stdout,4))[0]
                assert 0<length<=65536
                h=json.loads(exact(proc.stdout,length));size=h['bytes']
                assert 0<=size<=128*1024**2
                pixels=exact(proc.stdout,size)
                if h['type']=='error':raise RuntimeError(h['error'])
                if h['type'] in ('frame','preview'):
                    channels=4 if h['type']=='preview' else 3
                    assert size==h['width']*h['height']*channels
                    assert h['stride_bytes']==h['width']*channels
                    assert h['pixel_format']==('BGRA8' if channels==4 else 'RGB8')
                    assert h['capture_ns']>0 and h['qpc_frequency']>0
                    if h['type']=='preview':
                        assert h['width']<=1280 and h['height']<=720
                        assert h['source_width']>=h['width'] and h['source_height']>=h['height']
                    h['fixture_color_pixels']=sum(1 for i in range(0,len(pixels),13*channels)
                        if i+2<len(pixels) and ((pixels[i]>210 and pixels[i+1]<60 and pixels[i+2]<60)
                         or (pixels[i+1]>210 and pixels[i]<60 and pixels[i+2]<60)))
                events.put(h)
                if h['type']=='end':break
        except Exception as exc:failures.append(repr(exc))
        finally:done.set()
    thread=threading.Thread(target=read,daemon=True);thread.start()
    start=time.monotonic();changed=False
    try:
        while not done.is_set():
            root.update()
            canvas.itemconfigure('moving',fill='#ff0000' if int((time.monotonic()-start)*5)%2 else '#0000ff')
            if resize and not changed and time.monotonic()-start>1:
                root.geometry('760x470+100+100');changed=True
            if time.monotonic()-start>22:raise TimeoutError('Real WGC smoke timed out')
            time.sleep(.02)
        while not events.empty():records.append(events.get())
        proc.wait(timeout=5)
        errors=proc.stderr.read().decode('utf-8',errors='replace')
        assert not failures,(failures,errors)
        assert proc.returncode==0,errors
        frames=[x for x in records if x['type']=='frame']
        previews=[x for x in records if x['type']=='preview']
        assert len(frames)>=2,records
        assert len(previews)>=2,records
        assert all(b['capture_ns']>=a['capture_ns'] for a,b in zip(frames,frames[1:]))
        assert len({x['frame_id'] for x in frames})==len(frames)
        assert len({x['frame_id'] for x in previews})==len(previews)
        assert any(x['fixture_color_pixels']>10 for x in frames),'Owned colored window absent from capture'
        assert any(x['fixture_color_pixels']>10 for x in previews),'Owned colored window absent from preview'
        assert any(x['type']=='ready' and x['target']['id']==target['id'] for x in records)
        if resize:assert any(x['type']=='geometry_changed' for x in records),'Resize not registered'
        if target['kind']=='window':assert max(x['width'] for x in frames)<1000,'Captured desktop instead of selected window'
        return dict(target_kind=target['kind'],records=records,actual_wgc=True,
                    source='owned_synthetic_window_not_game',stderr=errors)
    finally:
        if proc.poll() is None:
            proc.stdin.write(b'stop\n');proc.stdin.flush()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        for pipe in (proc.stdin,proc.stdout,proc.stderr):pipe.close()
        thread.join(2)


def main():
    p=argparse.ArgumentParser();p.add_argument('--binary',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    if os.name!='nt':raise RuntimeError('Windows actual capture test required')
    root=tk.Tk();root.title('HM2 native capture verification');root.geometry('640x420+100+100')
    canvas=tk.Canvas(root,bg='#00ff00',highlightthickness=0);canvas.pack(fill='both',expand=True)
    canvas.create_rectangle(30,30,230,220,fill='#ff0000',outline='',tags='moving')
    root.update();time.sleep(.3);root.update()
    result={}
    try:
        targets=json.loads(subprocess.check_output([a.binary,'list'],timeout=10))
        windows=[x for x in targets if x['kind']=='window' and x['label']=='HM2 native capture verification']
        assert len(windows)==1,targets
        assert windows[0]['pid']==os.getpid()
        monitors=[x for x in targets if x['kind']=='monitor'];assert monitors
        result['window']=exercise(a.binary,windows[0],root,canvas,True)
        result['monitor']=exercise(a.binary,next((x for x in monitors if x['primary']),monitors[0]),root,canvas)
        result['monitors_available']=len(monitors);result['two_physical_monitors_tested']=len(monitors)>=2
        result['execution_complete']=True;result['tft_or_vanguard_tested']=False
        print('HM2_REAL_CAPTURE_SMOKE_OK',flush=True)
    finally:
        (out/'capture-smoke.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        root.destroy()

if __name__=='__main__':main()
