"""Mapping-first desktop; overlays always belong to the displayed analysis frame."""
from __future__ import annotations
from pathlib import Path
import argparse, json, os, queue, subprocess, sys, time
from datetime import datetime
from .core import crop_box, valid_box, dump
from .session import Options, Session

def paths():
    from e1.app import default_paths
    return default_paths()

def main():
    p=argparse.ArgumentParser(description='Agente TFT HUD Mapper — gravação local encerrada')
    p.add_argument('--headless',action='store_true');p.add_argument('--video');p.add_argument('--model');p.add_argument('--output')
    p.add_argument('--seconds',type=float,default=300);p.add_argument('--board-reference');p.add_argument('--controls')
    p.add_argument('--ui-smoke',action='store_true');p.add_argument('--train',action='store_true');p.add_argument('--dataset',action='append')
    p.add_argument('--steps',type=int,default=400);p.add_argument('--allow-weak',action='store_true')
    a=p.parse_args()
    if a.train:
        from .train import train
        train(a.dataset or [],a.model,a.output,a.steps,a.allow_weak)
        return 0
    if a.headless:
        s=Session(Options(**paths(),video=a.video,model=a.model,output=a.output,seconds=a.seconds,
                          board_reference=a.board_reference,controls=a.controls)).start()
        while not s.done.is_set():
            for q in (s.map_results,s.native_results):
                try:q.get(.005)
                except queue.Empty:pass
            time.sleep(.02)
        result=s.finish();print('HUD_MAPPER_SUMMARY='+json.dumps(result,ensure_ascii=False))
        print('HUD_MAPPER_COMPARISON='+str(Path(a.output)/'comparison.txt'))
        return 0 if result['execution_complete'] else 2
    import tkinter as tk
    root=tk.Tk();app=App(root)
    if a.ui_smoke:
        if not all((a.model,a.video,a.output)):p.error('ui-smoke requer --model --video --output')
        app.model.set(a.model);app.video.set(a.video);app.dest.set(str(Path(a.output).parent));app.seconds.set('2')
        app.smoke_output=a.output;app.smoke=True
        root.after(100,app.start)
    root.mainloop()
    if a.ui_smoke:
        return 0 if app.session and app.session.finished and not app.session.error and app.displayed>0 else 2
    return 0

class App:
    def __init__(self,root):
        import tkinter as tk
        from tkinter import ttk
        self.root=root;self.session=None;self.last={};self.photo=None;self.zoom_photo=None;self.displayed=0
        self.freeze=False;self.smoke=False;self.smoke_output=None;self.closing=False;self.training=None
        self.current=None;self.crop_current=None;self.last_paint=0;self.last_finished=None
        self.finalizing=False;self.final_result=None;self.training_dirs=[]
        root.title('Agente TFT — HUD Mapper HM1');root.geometry('1440x910');root.minsize(1100,750)
        style=ttk.Style(root);style.theme_use('clam');root.configure(bg='#111c25')
        for name in ('TFrame','TLabel','TLabelframe','TLabelframe.Label'):
            style.configure(name,background='#111c25',foreground='#dce7ef')
        style.configure('TButton',padding=5)
        self.video=tk.StringVar();self.model=tk.StringVar();self.dest=tk.StringVar();self.ref=tk.StringVar();self.controls=tk.StringVar()
        self.seconds=tk.StringVar(value='300');self.scenario=tk.StringVar(value='cenario-01')
        self.which=tk.StringVar(value='map');self.overlays=tk.BooleanVar(value=True)
        outer=ttk.Frame(root,padding=12);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='HUD MAPPER  /  Mapeamento e exemplos naturais',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(outer,text='Rede espacial + leitores existentes + pixels vinculados ao frame. Desempenho em segundo plano.').pack(anchor='w',pady=(2,8))
        self.row(outer,'Gravação local encerrada',self.video)
        self.row(outer,'Modelo L2/L3 (deployment-candidate.json)',self.model)
        self.row(outer,'Pasta de resultados',self.dest,True)
        self.row(outer,'Referência B1: JPEG do banco vazio (opcional)',self.ref)
        self.row(outer,'Perfil efetivo S4 de controles (opcional)',self.controls)
        line=ttk.Frame(outer);line.pack(fill='x',pady=4)
        for label,var,width in [('Cenário',self.scenario,24),('Duração (s)',self.seconds,6)]:
            ttk.Label(line,text=label).pack(side='left');ttk.Entry(line,textvariable=var,width=width).pack(side='left',padx=5)
        ttk.Button(line,text='Iniciar mapeamento',command=self.start).pack(side='left',padx=6)
        ttk.Button(line,text='Encerrar e salvar',command=self.stop).pack(side='left')
        ttk.Button(line,text='Motor / dicas de laboratório',command=self.engine_window).pack(side='right')
        self.status=ttk.Label(outer,text='Selecione a gravação, o modelo treinado e o destino. Nenhum programa de jogo é acessado.');self.status.pack(anchor='w',pady=5)
        tabs=ttk.Notebook(outer);tabs.pack(fill='both',expand=True)
        mapping=ttk.Frame(tabs);performance=ttk.Frame(tabs);training=ttk.Frame(tabs)
        tabs.add(mapping,text='HUD: mapa e leituras');tabs.add(performance,text='Desempenho / filas');tabs.add(training,text='Dados e treinamento')
        line=ttk.Frame(mapping);line.pack(fill='x')
        ttk.Radiobutton(line,text='Mapa neural + referências',variable=self.which,value='map',command=self.repaint).pack(side='left')
        ttk.Radiobutton(line,text='Leituras no próprio frame',variable=self.which,value='reader',command=self.repaint).pack(side='left',padx=8)
        ttk.Checkbutton(line,text='Mostrar recortes',variable=self.overlays,command=self.repaint).pack(side='left')
        ttk.Button(line,text='Congelar / retomar inspeção',command=self.toggle_freeze).pack(side='right')
        self.caption=ttk.Label(mapping,text='A imagem analisada e suas caixas têm sempre o mesmo frame_id.');self.caption.pack(anchor='w')
        split=ttk.Panedwindow(mapping,orient='horizontal');split.pack(fill='both',expand=True)
        left=ttk.Frame(split);right=ttk.Frame(split);split.add(left,weight=3);split.add(right,weight=2)
        self.canvas=tk.Canvas(left,bg='#070d12',highlightthickness=0,width=900,height=520);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda _:self.repaint())
        # Reserve crop/details; only the scrollable region table yields vertical space.
        right.columnconfigure(0,weight=1);right.rowconfigure(0,weight=1)
        columns=('region','status','value');self.table=ttk.Treeview(right,columns=columns,show='headings',height=4)
        for c,w in [('region',155),('status',180),('value',80)]:self.table.heading(c,text=c);self.table.column(c,width=w,minwidth=50)
        self.table.grid(row=0,column=0,sticky='nsew');self.table.bind('<<TreeviewSelect>>',self.selected)
        scroll=ttk.Scrollbar(right,orient='vertical',command=self.table.yview)
        scroll.grid(row=0,column=1,sticky='ns');self.table.configure(yscrollcommand=scroll.set)
        ttk.Label(right,text='Clique numa região para ver o recorte original e a origem.',wraplength=400).grid(row=1,column=0,columnspan=2,sticky='ew')
        self.crop_label=ttk.Label(right,anchor='center');self.crop_label.grid(row=2,column=0,columnspan=2,sticky='ew')
        self.details=tk.Text(right,height=5,bg='#172934',fg='#dce7ef',wrap='word')
        self.details.grid(row=3,column=0,columnspan=2,sticky='ew')
        self.perf=tk.Text(performance,bg='#172934',fg='#dce7ef',wrap='word');self.perf.pack(fill='both',expand=True)
        ttk.Label(training,text='A sessão salva PNGs nativos, recortes, leituras, propostas neurais e tempos.\nPredições não são gabaritos. A coleta não altera os pesos.',justify='left').pack(anchor='w',pady=10)
        ttk.Button(training,text='Abrir última sessão',command=self.open_output).pack(anchor='w',pady=4)
        ttk.Button(training,text='Preparar sementes por referências visuais',command=self.prepare_seeds).pack(anchor='w',pady=4)
        ttk.Button(training,text='Adicionar outra sessão ao treino',command=self.add_training_session).pack(anchor='w',pady=4)
        ttk.Button(training,text='Treinar candidata após a sessão',command=self.train).pack(anchor='w',pady=4)
        self.train_info=ttk.Label(training,text='Treino separado do caminho rápido. Requer weights.npz junto do modelo\ne sementes explícitas para os dois painéis; dados desconhecidos ficam sem alvo.',justify='left')
        self.train_info.pack(anchor='w',pady=10)
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(40,self.tick)
    def row(self,parent,label,var,directory=False):
        from tkinter import ttk,filedialog
        line=ttk.Frame(parent);line.pack(fill='x',pady=2)
        ttk.Label(line,text=label,width=49).pack(side='left');ttk.Entry(line,textvariable=var).pack(side='left',fill='x',expand=True)
        def choose():
            p=filedialog.askdirectory() if directory else filedialog.askopenfilename()
            if p:var.set(p)
        ttk.Button(line,text='Escolher',command=choose).pack(side='right')
    def start(self):
        from tkinter import messagebox
        if self.finalizing or (self.session and not self.session.finished):return
        if self.training and self.training.poll() is None:
            messagebox.showerror('HUD Mapper','Encerre o treinamento antes de outra sessão.');return
        try:
            if not self.dest.get():raise ValueError('Escolha um destino com espaço livre.')
            out=self.smoke_output or str(Path(self.dest.get())/('hud-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
            self.session=Session(Options(**paths(),video=self.video.get(),model=self.model.get(),output=out,
               seconds=float(self.seconds.get()),scenario=self.scenario.get(),controls=self.controls.get() or None,
               board_reference=self.ref.get() or None)).start()
            self.last={};self.freeze=False;self.current=None
        except Exception as exc:messagebox.showerror('HUD Mapper',str(exc))
    def stop(self):
        if self.session and not self.session.done.is_set():self.session.stop()
    def close(self):
        self.closing=True;self.stop()
        if self.training and self.training.poll() is None:
            self.training.terminate()
        if (not self.session or self.session.finished) and not self.finalizing:self.root.destroy()
    def toggle_freeze(self):self.freeze=not self.freeze;self.repaint()
    def engine_window(self):
        import tkinter as tk
        from e1.app import App as EngineApp
        EngineApp(tk.Toplevel(self.root))
    def repaint(self):
        if self.freeze and self.current:item=self.current
        else:item=self.last.get(self.which.get())
        if not item:return
        from PIL import Image,ImageTk,ImageDraw
        previous=self.current
        self.current=item;f=item['frame'];r=item['record'];view=item.get('view_kind',self.which.get())
        if previous is None or previous['frame'].id!=f.id:
            self.crop_label.configure(image='',text='Selecione uma região deste frame.')
            self.details.delete('1.0','end')
        im=Image.frombytes('RGB',(f.width,f.height),f.rgb)
        if self.overlays.get():
            draw=ImageDraw.Draw(im)
            regions=r['regions']
            if view=='map' and self.session.registry:
                regions=self.session.registry.fixed(f.width,f.height)+regions
            for reg in regions:
                for cell in reg.get('guide_points',[]):
                    x,y=cell['screen'];draw.ellipse((x-4,y-4,x+4,y+4),outline='#bb91ff',width=2)
                b=reg.get('box')
                if not b or not valid_box(b,f.width,f.height):continue
                color='#ffcf70' if str(reg['id']).startswith('neural.') else '#53d7d0'
                draw.rectangle(b,outline=color,width=2)
                draw.text((b[0]+2,max(0,b[1]-13)),reg['id'],fill=color)
        w=max(100,self.canvas.winfo_width()-8);h=max(100,self.canvas.winfo_height()-8)
        im.thumbnail((w,h),Image.Resampling.BILINEAR);self.photo=ImageTk.PhotoImage(im)
        self.canvas.delete('all');self.canvas.create_image(w//2,h//2,image=self.photo,anchor='center')
        self.caption.configure(text=f"{'INSPEÇÃO CONGELADA · ' if self.freeze else ''}Frame {f.id} · vídeo {f.pts_ms/1000:.3f}s · {f.width}×{f.height} · caixas deste frame, não da prévia atual")
        self.table.delete(*self.table.get_children());self.row_data={}
        shown=r['regions']
        if view=='map' and self.session.registry:shown=self.session.registry.fixed(f.width,f.height)+shown
        for i,reg in enumerate(shown):
            rid=str(i);self.row_data[rid]=reg
            value=reg.get('value');self.table.insert('', 'end',iid=rid,values=(reg['id'],reg['status'],'' if value is None else str(value)[:80]))
        self.displayed+=1
    def selected(self,_=None):
        if not self.current or not self.table.selection():return
        from PIL import Image,ImageTk
        reg=self.row_data[self.table.selection()[0]];f=self.current['frame'];b=reg.get('box')
        self.details.delete('1.0','end');self.details.insert('end',json.dumps(reg,ensure_ascii=False,indent=2))
        if b and valid_box(b,f.width,f.height):
            im=Image.frombytes('RGB',(f.width,f.height),f.rgb).crop(crop_box(b,f.width,f.height))
            if im.width<100:im=im.resize((im.width*3,im.height*3),Image.Resampling.NEAREST)
            im.thumbnail((460,140),Image.Resampling.BILINEAR);self.zoom_photo=ImageTk.PhotoImage(im);self.crop_label.configure(image=self.zoom_photo,text='')
        else:self.crop_label.configure(image='',text='Sem região válida; nenhum recorte inventado.')
    def open_output(self):
        if not self.last_finished:return
        p=Path(self.last_finished)
        if os.name=='nt':os.startfile(str(p))
        else:subprocess.Popen(['xdg-open',str(p)])
    def prepare_seeds(self):
        from tkinter import messagebox
        if not self.last_finished:
            messagebox.showinfo('Dados','Encerre uma sessão de HUD primeiro.');return
        try:
            from .seeds import prepare
            result=prepare(Path(self.last_finished))
            self.train_info.configure(text=json.dumps(result,ensure_ascii=False,indent=2))
        except Exception as e:messagebox.showerror('Sementes',str(e))
    def add_training_session(self):
        from tkinter import filedialog,messagebox
        p=filedialog.askdirectory(title='Sessão HUD encerrada, com supervision/weak-seeds.json')
        if p and Path(p,'COMPLETE.json').is_file():
            self.training_dirs.append(p);self.train_info.configure(text='Sessões adicionais: '+str(len(self.training_dirs)))
        elif p:messagebox.showerror('Treino','Não é uma sessão completa do HUD Mapper.')
    def train(self):
        from tkinter import messagebox,filedialog
        if self.session and not self.session.finished:
            messagebox.showerror('Treino','Encerre a sessão; treino não roda junto da coleta.');return
        if self.training and self.training.poll() is None:return
        if not self.last_finished:return
        if not messagebox.askyesno('Treino experimental',
           'Treinar com sementes de referências visuais? Elas são supervisão fraca, não gabarito.\nA candidata NÃO substituirá os leitores.'):return
        try:
            if not Path(self.model.get()).with_name('weights.npz').is_file():raise ValueError('Copie weights.npz da MESMA execução junto de deployment-candidate.json.')
            output=str(Path(self.last_finished).parent/('candidate-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
            args=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).parents[1]/'AgenteTFT_HUD.py')]
            from .seeds import prepare
            for folder in dict.fromkeys([self.last_finished]+self.training_dirs):
                if not Path(folder,'supervision/weak-seeds.json').is_file():prepare(folder)
            args+=['--train','--model',self.model.get(),'--output',output,'--allow-weak']
            for folder in dict.fromkeys([self.last_finished]+self.training_dirs):args+=['--dataset',folder]
            log_path=Path(self.last_finished).parent/(Path(output).name+'-train.log')
            with log_path.open('xb') as log:
                self.training=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT)
            self.train_info.configure(text='Treinamento separado iniciado. Resultado: '+output+'\nLog: '+str(log_path))
        except Exception as e:messagebox.showerror('Treino',str(e))
    def tick(self):
        s=self.session
        if s and not s.finished and not self.finalizing:
            for name,q in [('map',s.map_results),('reader',s.native_results)]:
                try:
                    item=q.get(.001);item['view_kind']=name;self.last[name]=item
                    if not self.freeze and self.which.get()==name:
                        self.repaint();s.acknowledge(item,name)
                except queue.Empty:pass
            self.status.configure(text=f"{s.phase} · rede {s.counts['mapped_frames']} · leituras {s.counts['read_frames']} · PNGs {s.store.counts['samples_saved']}")
            text=dict(frames=dict(s.counts),mapper_queue_replaced=s.map_pending.replaced,native_queue_replaced=s.native_pending.replaced,
                      coverage=[dict(region=k[0],status=k[1],count=v) for k,v in list(s.coverage.items())],
                      note='Proposta de localização não certifica pixels corretos. Dicas e desempenho são auxiliares.')
            self.perf.delete('1.0','end');self.perf.insert('end',json.dumps(text,ensure_ascii=False,indent=2))
            if s.done.is_set() and s.map_results.empty() and s.native_results.empty():
                import threading
                self.finalizing=True;self.status.configure(text='Selando amostras e relatório, sem bloquear a interface…')
                def finalize():
                    try:self.final_result=s.finish()
                    except Exception as exc:self.final_result=dict(execution_complete=False,error=str(exc))
                threading.Thread(target=finalize,daemon=True).start()
        if self.finalizing and self.final_result is not None:
            result=self.final_result;self.final_result=None;self.finalizing=False;self.last_finished=s.options.output
            self.status.configure(text=('Concluído' if result['execution_complete'] else 'Parcial: '+str(result['error']))+' — '+s.options.output)
            self.perf.delete('1.0','end');self.perf.insert('end',json.dumps(result,ensure_ascii=False,indent=2))
            if self.smoke or self.closing:self.root.destroy();return
        elif self.closing and not self.finalizing and (not s or s.finished):self.root.destroy();return
        self.root.after(80,self.tick)
