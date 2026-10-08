"""Six-minute WGC -> bounded IPC queue -> production Windows DIB endurance.

An animated, high-entropy owned window exercises preview without collecting
any desktop content. This isolates transport/drawing, not whole-match accuracy.
"""
import argparse
import json
from pathlib import Path
import queue
import random
import statistics
import time
import tkinter as tk
from PIL import Image, ImageTk
from hm.capture_source import CaptureSource, list_targets
from hm.native_preview import NativePreview
from hm.process_memory import current_process_memory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=330)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=tk.Tk();root.title('TFT owned preview endurance');root.geometry('1280x720+0+0')
    source=tk.Canvas(root,highlightthickness=0);source.pack(fill='both',expand=True)
    pixels=random.Random(20261004).randbytes(1280*720*3)
    picture=ImageTk.PhotoImage(Image.frombytes('RGB',(1280,720),pixels))
    source.create_image(0,0,image=picture,anchor='nw')
    marker=source.create_rectangle(0,50,100,150,fill='#8c50ff',outline='')
    window=tk.Toplevel(root);window.title('TFT preview destination');window.geometry('640x360+500+300')
    canvas=tk.Canvas(window,highlightthickness=0);canvas.pack(fill='both',expand=True)
    root.update()
    configs=Path('configs').resolve()
    target=next(r for r in list_targets(configs) if r['kind']=='window' and r['label']=='TFT owned preview endurance')
    capture=None;rows=[];draws=[];ages=[];error=None
    stages={key: [] for key in ('gpu_copy_and_map_ms', 'bgra_rgb_ms',
                                'previous_ipc_write_ms', 'capture_age_before_ipc_ms')}
    delivery_ms=[];frame_gaps_ms=[];previous_frame_due=None
    try:
        capture=CaptureSource(f'capture://window/{target["id"]}',configs,args.seconds,2,
                              consent=True,expected=target,preview_hz=30,preview_size=(1280,720))
        renderer=NativePreview();started=time.perf_counter();last=started;count=0;previous_count=0
        while not capture.reader_done.is_set():
            elapsed=time.perf_counter()-started
            if elapsed>args.seconds+20:raise TimeoutError('Capture endurance did not finish')
            x=int(elapsed*240)%1150
            source.coords(marker,x,50,x+100,150);root.update()
            try:
                frame=capture.preview_frames.get(0)
                if frame.capture['pixel_format']!='BGRA8':raise ValueError('Preview channel conversion returned')
                draw_start=time.perf_counter()
                renderer.draw(canvas,frame.width,frame.height,frame.rgb)
                draws.append((time.perf_counter()-draw_start)*1000)
                ages.append((time.perf_counter_ns()-frame.due_ns)/1e6)
                delivery_ms.append((frame.ready_ns-frame.due_ns)/1e6)
                for key, values in stages.items():
                    value=frame.capture.get(key)
                    if isinstance(value,(int,float)):values.append(value)
                if previous_frame_due is not None:
                    frame_gaps_ms.append((frame.due_ns-previous_frame_due)/1e6)
                previous_frame_due=frame.due_ns
                count+=1
            except queue.Empty:
                pass
            now=time.perf_counter()
            if now-last>=1:
                rows.append(dict(seconds=now-started,fps=(count-previous_count)/(now-last),
                                 memory=current_process_memory()))
                previous_count=count;last=now
            time.sleep(.005)
        if capture.error:raise RuntimeError(capture.error)
        if not capture.end or not capture.end.get('execution_complete'):raise RuntimeError('Capture incomplete')
    except Exception as exc:
        error=str(exc)
    finally:
        if capture:capture.close()
        root.destroy()
    early=[r for r in rows if 20<=r['seconds']<=50]
    late=rows[-30:]
    first=statistics.mean(r['fps'] for r in early) if early else 0
    last=statistics.mean(r['fps'] for r in late) if late else 0
    memory_delta=(late[-1]['memory']['private_bytes']-early[0]['memory']['private_bytes']) if early and late else None
    def p95(values):
        ordered=sorted(values)
        return ordered[int((len(ordered)-1)*.95)] if ordered else None
    report=dict(scope='preview_transport_and_drawing_only',seconds=args.seconds,
        source='owned_high_entropy_animated_window',target_fps=30,early_fps=first,late_fps=last,
        render_p95_ms=p95(draws),
        private_memory_delta_bytes=memory_delta,rows=rows,error=error,
        whole_application_or_user_pc_validated=False,
        source_to_draw_p95_ms=p95(ages),
        native_stage_p95_ms={key:p95(values) for key,values in stages.items()},
        ipc_delivery_p95_ms=p95(delivery_ms),
        drawn_frame_gap_p95_ms=p95(frame_gaps_ms),
        drawn_gaps_over_66ms=sum(gap>66 for gap in frame_gaps_ms),
        native_preview_received=capture.preview_received if capture else None,
        preview_queue_replaced=capture.preview_frames.replaced if capture and capture.preview_frames else None,
        native_end=capture.end if capture else None)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)
    if error or last<20 or last<first*.85 or memory_delta is None or memory_delta>64*1024*1024:
        raise RuntimeError('Preview endurance gate failed; inspect report')


if __name__=='__main__':main()
