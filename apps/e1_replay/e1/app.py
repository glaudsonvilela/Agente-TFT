"""Small desktop replay UI. Tk updated only by its owning thread, never by OCR."""
from __future__ import annotations
import argparse, json, os, queue, sys, time
from pathlib import Path
from datetime import datetime
from .pipeline import Options, Session


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[3]))


def default_paths():
    root = resource_root()
    exe = '.exe' if os.name == 'nt' else ''
    bundled = root / 'bin' / ('agente-tft-e1-worker' + exe)
    worker = bundled if bundled.is_file() else root/'tools/e1-native/target/release'/('agente-tft-e1-worker'+exe)
    ff = root/'ffmpeg' / ('ffmpeg'+exe)
    fp = root/'ffmpeg' / ('ffprobe'+exe)
    tess = root/'tesseract'/('tesseract'+exe)
    if tess.exists():
        os.environ['TESSDATA_PREFIX'] = str(tess.parent/'tessdata')
    os.environ.setdefault('OMP_THREAD_LIMIT', '1')
    return dict(worker=str(worker), configs=str(root/'configs'),
                tesseract=str(tess) if tess.exists() else 'tesseract',
                ffmpeg=str(ff) if ff.exists() else 'ffmpeg', ffprobe=str(fp) if fp.exists() else 'ffprobe')


def headless(args):
    o = Options(**default_paths(), mode=args.mode, video=args.video, output=args.output,
                seconds=args.seconds, reader_hz=args.reader_hz, injected_wait_ms=args.injected_wait_ms,
                model=args.model, board_reference=args.board_reference, controls=args.controls)
    s = Session(o).start()
    try:
        while not s.done.is_set() or not s.results.empty():
            try:
                r = s.results.get(.05)
                s.acknowledge(r, 'headless_sink_not_UI')
            except queue.Empty:
                pass
        result = s.finish()
    except KeyboardInterrupt:
        s.stop(); s.thread.join(20); result = s.finish()
    print('E1_SUMMARY=' + json.dumps(result, ensure_ascii=False))
    print('E1_COMPARISON=' + str(Path(args.output)/'comparison.txt'))
    return 0 if result['execution_complete'] else 2


class App:
    def __init__(self, root, smoke_output=None):
        import tkinter as tk
        from tkinter import ttk
        self.root = root; self.session = None; self.last = None; self.photo = None
        self.closing = False; self.preview_ns = 0
        root.title('Agente TFT — E1 Replay Lab'); root.geometry('1220x830'); root.minsize(950, 720)
        root.configure(background='#101820')
        style = ttk.Style(root); style.theme_use('clam')
        style.configure('TFrame', background='#101820'); style.configure('TLabel', background='#101820', foreground='#e4eef7')
        style.configure('TButton', padding=6)
        self.mode = tk.StringVar(value='fixtures'); self.video = tk.StringVar()
        self.dest = tk.StringVar(value=''); self.model = tk.StringVar(); self.reference = tk.StringVar(); self.controls = tk.StringVar()
        self.seconds = tk.StringVar(value='30'); self.hz = tk.StringVar(value='2'); self.stress = tk.BooleanVar(value=False)
        outer=ttk.Frame(root,padding=18);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='AGENTE TFT  /  E1',font=('Segoe UI',19,'bold')).pack(anchor='w')
        ttk.Label(outer,text='Laboratório de replay encerrado · sem captura de partida ao vivo · dados reais e cenários separados').pack(anchor='w',pady=(2,12))
        line=ttk.Frame(outer);line.pack(fill='x')
        ttk.Radiobutton(line,text='Cenários controlados → motor Rust real',variable=self.mode,value='fixtures').pack(side='left')
        ttk.Radiobutton(line,text='Vídeo local → percepção real',variable=self.mode,value='replay').pack(side='left',padx=18)
        self.file_row(outer,'Vídeo encerrado',self.video,False)
        self.file_row(outer,'Pasta de resultados',self.dest,True)
        self.file_row(outer,'UI-Map opcional (deployment-candidate.json)',self.model,False)
        self.file_row(outer,'Referência B1 opcional (JPEG do banco vazio)',self.reference,False)
        self.file_row(outer,'Controles opcionais (perfil efetivo S4)',self.controls,False)
        line=ttk.Frame(outer);line.pack(fill='x',pady=8)
        ttk.Label(line,text='Duração (s):').pack(side='left');ttk.Entry(line,textvariable=self.seconds,width=6).pack(side='left',padx=5)
        ttk.Label(line,text='Leitor (Hz):').pack(side='left');ttk.Entry(line,textvariable=self.hz,width=5).pack(side='left',padx=5)
        ttk.Checkbutton(line,text='Stress explícito: +600 ms por tarefa',variable=self.stress).pack(side='left',padx=10)
        ttk.Button(line,text='Iniciar sessão',command=self.start).pack(side='right',padx=5)
        ttk.Button(line,text='Encerrar',command=self.stop).pack(side='right')
        self.status=ttk.Label(outer,text='Selecione um destino. Nenhum treinamento ou instalação será iniciado.');self.status.pack(anchor='w')
        area=ttk.Frame(outer);area.pack(fill='both',expand=True,pady=10)
        self.image=ttk.Label(area,text='Modo controlado: não há imagem nem OCR simulados.',anchor='center');self.image.pack(side='left',fill='both',expand=True)
        panel=ttk.Frame(area,padding=12);panel.pack(side='right',fill='both',expand=True)
        self.tip=ttk.Label(panel,text='Aguardando entrada',font=('Segoe UI',15,'bold'),wraplength=410);self.tip.pack(anchor='w',pady=8)
        self.info=ttk.Label(panel,text='',wraplength=410,justify='left');self.info.pack(anchor='w')
        self.metrics=ttk.Label(panel,text='',wraplength=410,justify='left');self.metrics.pack(anchor='w',pady=12)
        self.detail=tk.Text(panel,height=12,width=52,bg='#172631',fg='#dcebf5',font=('Consolas',9),wrap='word')
        self.detail.pack(fill='both',expand=True)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(20,self.tick)
        if smoke_output:
            self.dest.set(str(Path(smoke_output).parent));self.seconds.set('2')
            root.after(100,lambda:self.start(exact_output=smoke_output))
            self.closing_after_run=True
        else:self.closing_after_run=False

    def file_row(self,parent,label,var,directory):
        from tkinter import ttk,filedialog
        row=ttk.Frame(parent);row.pack(fill='x',pady=2)
        ttk.Label(row,text=label,width=43).pack(side='left')
        ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
        def choose():
            p=filedialog.askdirectory() if directory else filedialog.askopenfilename()
            if p:var.set(p)
        ttk.Button(row,text='Escolher',command=choose).pack(side='right',padx=5)

    def start(self,exact_output=None):
        from tkinter import messagebox
        if self.session and not self.session.finished:
            return
        try:
            if not self.dest.get():raise ValueError('Escolha uma pasta gravável com espaço livre.')
            output=exact_output or str(Path(self.dest.get())/('e1-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
            opts=Options(**default_paths(),output=output,mode=self.mode.get(),video=self.video.get() or None,
                         seconds=float(self.seconds.get()),reader_hz=float(self.hz.get()),
                         injected_wait_ms=600 if self.stress.get() else 0,model=self.model.get() or None,
                         board_reference=self.reference.get() or None,controls=self.controls.get() or None)
            self.session=Session(opts).start();self.last=None
            self.status.configure(text='Preparando trabalhadores residentes…')
        except Exception as e:messagebox.showerror('E1',str(e))

    def stop(self):
        if self.session and not self.session.done.is_set():self.session.stop()
    def close(self):
        self.closing=True;self.stop()
        if not self.session or self.session.finished:self.root.destroy()

    def tick(self):
        from PIL import Image,ImageTk
        s=self.session
        if s and not s.finished:
            try:
                f=s.preview.get(.001)
                if f.rgb:
                    t=time.perf_counter_ns();im=Image.frombytes('RGB',(f.width,f.height),f.rgb);im.thumbnail((650,370),Image.Resampling.BILINEAR)
                    self.photo=ImageTk.PhotoImage(im);self.image.configure(image=self.photo,text='')
                    s.emit('preview_applied',frame_id=f.id,ui_cpu_ms=(time.perf_counter_ns()-t)/1e6,
                           source_age_ms=(time.perf_counter_ns()-f.due_ns)/1e6)
            except queue.Empty:pass
            try:
                r=s.results.get(.001);self.last=r
                self.tip.configure(text=r['text'])
                a=r['answer'];vals={x['field']:x['value'] for x in (a.get('hud') or [])}
                self.info.configure(text=f"Origem: {a['origin']}\nFrame: {a['id']} · tempo do vídeo: {a['source_ms']/1000:.3f}s\nHUD: {vals or 'não executado no modo controlado'}\nOportunidades: {len(a['report']['all'])}")
                text=json.dumps({'spans':a['spans'],'blockers':a['blockers'],'decision':a['decision']},ensure_ascii=False,indent=2)
                self.detail.delete('1.0','end');self.detail.insert('end',text)
                # An application acknowledgement, not a physical scanout timestamp.
                s.acknowledge(r)
            except queue.Empty:pass
            if self.last:
                trace=self.last['trace'];age=(time.perf_counter_ns()-trace['source_due_ns'])/1e6
                expired=age>s.options.max_age_ms
                if expired:self.tip.configure(text='RESULTADO EXPIRADO — aguarde uma observação nova.')
                self.metrics.configure(text=f"Idade da fonte: {age:.0f} ms\nFila: {trace['queue_ms']:.1f} ms\nWorker + IPC: {trace['native_roundtrip_ms']:.1f} ms\nAté aplicação na UI: {trace.get('ui_applied_latency_ms',0):.1f} ms\nExibição física: não medida")
            self.status.configure(text=f"Frames: {s.counts['source_frames']} | processados: {s.counts['processed']} | substituídos na fila: {s.counts['reader_pending_superseded']}")
            if s.done.is_set() and s.results.empty():
                report=s.finish();self.status.configure(text=f"{'Concluído' if report['execution_complete'] else 'Parcial/erro'} — {s.options.output}/comparison.txt")
                if s.error:self.tip.configure(text='ERRO: '+s.error)
                if self.closing or self.closing_after_run:
                    self.root.destroy();return
        elif self.closing:
            self.root.destroy();return
        self.root.after(20,self.tick)


def main():
    p=argparse.ArgumentParser(description='Agente TFT E1 — replay local encerrado, não captura ao vivo.')
    p.add_argument('--headless',action='store_true');p.add_argument('--ui-smoke',action='store_true')
    p.add_argument('--mode',choices=['fixtures','replay'],default='fixtures')
    p.add_argument('--video');p.add_argument('--output');p.add_argument('--seconds',type=float,default=12)
    p.add_argument('--reader-hz',type=float,default=2);p.add_argument('--injected-wait-ms',type=float,default=0)
    p.add_argument('--model');p.add_argument('--board-reference');p.add_argument('--controls')
    a=p.parse_args()
    if a.headless:
        if not a.output:p.error('--output obrigatório')
        return headless(a)
    import tkinter as tk
    root=tk.Tk();app=App(root,a.output if a.ui_smoke else None);root.mainloop()
    if a.ui_smoke:
        if not app.session or not app.session.finished or app.session.error or app.session.counts['ui_applied']<1:return 2
    return 0
