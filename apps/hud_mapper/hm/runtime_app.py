"""HUD runtime shared by HM3 and the simplified HM4 automatic shell."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from collections import deque
import argparse, json, os, queue, statistics, sys, threading, time
from .core import crop_box, valid_box
from .runtime_session import RuntimeSession, HM4RuntimeSession
from .session import Options
from .capture_source import list_targets

def runtime_paths():
    root=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[3]))
    exe=".exe" if os.name=="nt" else ""
    tess=root/"tesseract"/("tesseract"+exe)
    if tess.is_file():
        os.environ["TESSDATA_PREFIX"]=str(tess.parent/"tessdata")
        tess_cmd=str(tess)
    else:
        tess_cmd="tesseract"
    bundled=root/"bin"/("agente-tft-e1-worker"+exe)
    native=root/"tools/e1-native/target/release"/("agente-tft-e1-worker"+exe)
    worker=bundled if bundled.is_file() else native
    os.environ.setdefault("OMP_THREAD_LIMIT","1")
    return dict(worker=str(worker),configs=str(root/"configs"),tesseract=tess_cmd,
                ffmpeg="HM3_RUNTIME_DISABLED",ffprobe="HM3_RUNTIME_DISABLED")

def _valid_candidate_model(meta):
    try:
        p=Path(meta);m=json.loads(p.read_text(encoding="utf-8-sig"))
        model=p.parent/"candidate-model.onnx"
        return (p.is_file() and model.is_file() and model.stat().st_size<=8*1024**2 and
                m.get("schema_version")==2 and m.get("coordinate_format")=="normalized_tlbr" and
                m.get("panels")==["bench","shop"])
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        return False

def discover_model():
    home=Path(os.environ.get("USERPROFILE") or Path.home())
    local=Path(os.environ.get("LOCALAPPDATA") or home)
    frozen=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[3]
    bundle=Path(getattr(sys,"_MEIPASS",frozen))
    candidates=[]
    override=os.environ.get("AGENTE_TFT_MODEL")
    if override:candidates.append(Path(override))
    candidates += [
        bundle/"models"/"deployment-candidate.json",
        frozen/"models"/"deployment-candidate.json",
        local/"AgenteTFT-HUD-HM4"/"models"/"deployment-candidate.json",
        local/"AgenteTFT-HUD-HM3"/"models"/"deployment-candidate.json",
        local/"AgenteTFT"/"models"/"deployment-candidate.json",
        home/"Documents"/"AgenteTFT"/"models"/"deployment-candidate.json",
    ]
    seen=set()
    for p in candidates:
        try:key=str(p.resolve())
        except OSError:key=str(p)
        if key in seen:continue
        seen.add(key)
        if _valid_candidate_model(p):return str(p)
    return ""

def default_hm4_output_root():
    base=Path(os.environ.get("LOCALAPPDATA") or Path.home())/"AgenteTFT-HUD-HM4"/"sessions"
    base.mkdir(parents=True,exist_ok=True)
    return str(base)

def target_label(t):
    b=t["bounds"];size=f'{b[2]-b[0]}×{b[3]-b[1]}'
    if t["kind"]=="monitor":
        return f'{t["device"]} · {t["label"]} · {size} · {t.get("adapter") or "adaptador não informado"}'
    hint=" · provável TFT/LoL" if t.get("candidate_tft") else ""
    return f'{t["label"]} · {size}{hint}'

def pct(values,q):
    if not values:return None
    a=sorted(float(v) for v in values);i=(len(a)-1)*q;lo=int(i);hi=min(lo+1,len(a)-1);f=i-lo
    return a[lo]*(1-f)+a[hi]*f

class App:
    def __init__(self,root,mode="hm3"):
        import tkinter as tk
        from tkinter import ttk
        self.root=root;self.mode=mode;self.hm4=mode=="hm4";self.session=None;self.selection=None;self.last={};self.current=None
        self.vm_core=self.hm4 and (Path(sys.executable).resolve().parent/"core/core-package.json").is_file()
        self.photo=self.zoom_photo=None;self.photo_size=None;self.freeze=False;self.finalizing=False;self.final_result=None
        self.last_finished=None;self.closing=False;self.displayed=0;self.smoke=False;self.smoke_output=None
        self.canvas_image=None;self._table_key=None;self._next_metrics_ns=0
        self.tip_history=deque(maxlen=100);self.tip_label=None
        self._next_preview_ns=0
        self.render_ms=deque(maxlen=120);self.preview_times=deque(maxlen=120)
        self.voice=None
        if self.hm4:
            from .voice import VoiceCoach
            self.voice=VoiceCoach()
        root.title("Agente TFT — "+("Revisão de replay" if self.hm4 else "HM3 Runtime"));root.geometry("1500x950" if self.hm4 else "1440x900");root.minsize(1120,760);root.configure(bg="#f6f3ff" if self.hm4 else "#101820")
        style=ttk.Style(root);style.theme_use("clam")
        if self.hm4:
            for name in ("TFrame","TLabel","TLabelframe","TLabelframe.Label"):
                style.configure(name,background="#f6f3ff",foreground="#252045")
            style.configure("TButton",padding=7,background="#6b50b8",foreground="#ffffff",bordercolor="#6b50b8")
            style.map("TButton",background=[("active","#8b6bd4")])
            style.configure("TCheckbutton",background="#f6f3ff",foreground="#252045")
            style.configure("TRadiobutton",background="#f6f3ff",foreground="#252045")
            style.configure("TNotebook",background="#ebe5fc",borderwidth=0)
            style.configure("TNotebook.Tab",padding=(16,9),background="#e9e2fa",foreground="#352b60")
            style.map("TNotebook.Tab",background=[("selected","#ffffff")],foreground=[("selected","#6545b4")])
            style.configure("Treeview",background="#ffffff",fieldbackground="#ffffff",foreground="#252045",rowheight=27)
            style.configure("Treeview.Heading",background="#e9e2fa",foreground="#352b60")
        else:
            for name in ("TFrame","TLabel","TLabelframe","TLabelframe.Label"):
                style.configure(name,background="#101820",foreground="#dce7ef")
            style.configure("TButton",padding=5)
        self.model=tk.StringVar();self.dest=tk.StringVar();self.ref=tk.StringVar();self.controls=tk.StringVar()
        self.seconds=tk.StringVar(value="7200" if self.hm4 else "300");self.scenario=tk.StringVar(value="hm4-replay-screen" if self.hm4 else "hud-live-01")
        self.map_hz=tk.StringVar(value="2" if self.hm4 else "8");self.reader_hz=tk.StringVar(value="2" if self.hm4 else "1");self.sample_hz=tk.StringVar(value="1")
        self.replay_review=tk.BooleanVar(value=False)
        self.voice_enabled=tk.BooleanVar(value=False)
        self.voice_choice=tk.StringVar(value=self.voice.voices.get(self.voice.voice_id, "Sem vozes instaladas") if self.voice else "")
        self.which=tk.StringVar(value="capture" if self.hm4 else "map");self.overlays=tk.BooleanVar(value=True)
        outer=ttk.Frame(root,padding=12);outer.pack(fill="both",expand=True)
        if self.hm4:
            from PIL import Image
            hero_path=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))/"assets/hm4-replay-hero-v1.png"
            self.hero_source=Image.open(hero_path).convert("RGB") if hero_path.is_file() else None
            self.hero=tk.Canvas(outer,height=155,bg="#eee8ff",highlightthickness=0)
            self.hero.pack(fill="x",pady=(0,10))
            self.hero.bind("<Configure>",self.render_hero)
        else:
            ttk.Label(outer,text="AGENTE TFT  /  HUD MAPPER HM3",font=("Segoe UI",18,"bold")).pack(anchor="w")
            ttk.Label(outer,text="Objetivo principal: mapear a HUD ao vivo. Captura Rust → rede ONNX → leitores → telemetria; performance sempre visível.").pack(anchor="w",pady=(2,8))
        source=ttk.Frame(outer);source.pack(fill="x",pady=2)
        ttk.Label(source,text="Fonte de pixels",width=35).pack(side="left")
        self.source_label=ttk.Label(source,text="Nenhum monitor/janela selecionado",anchor="w");self.source_label.pack(side="left",fill="x",expand=True)
        ttk.Button(source,text="Detectar TFT",command=lambda:self.choose_source(True)).pack(side="right",padx=3)
        ttk.Button(source,text="Escolher monitor/janela",command=self.choose_source).pack(side="right")
        line=ttk.Frame(outer);line.pack(fill="x",pady=4)
        if self.hm4:
            auto=discover_model();self.model.set(auto);self.dest.set(default_hm4_output_root())
            ttk.Label(line,text=("Modelo para revisão: "+Path(auto).parent.name if auto else "Modelo neural não encontrado: captura + leitores nativos continuam ativos.")).pack(side="left")
            ttk.Checkbutton(line,text="Revisar vídeo encerrado (HUB + dicas)",variable=self.replay_review).pack(side="left",padx=8)
            ttk.Checkbutton(line,text="Narrar orientações",variable=self.voice_enabled,
                            command=lambda:self.voice.set_enabled(self.voice_enabled.get())).pack(side="left",padx=8)
            ttk.Label(line,text="Voz").pack(side="left")
            self.voice_picker=ttk.Combobox(line,textvariable=self.voice_choice,state="readonly",width=18,
                                          values=tuple(self.voice.voices.values()))
            self.voice_picker.pack(side="left",padx=3)
            self.voice_picker.bind("<<ComboboxSelected>>",self.choose_voice)
            ttk.Button(line,text="Testar voz",command=self.test_voice).pack(side="left",padx=2)
            ttk.Button(line,text="Calibrar tabuleiro",command=self.calibrate_board).pack(side="right",padx=4)
            ttk.Button(line,text="INICIAR",command=self.start).pack(side="right",padx=8)
            ttk.Button(line,text="ENCERRAR",command=self.stop).pack(side="right")
        else:
            self.file_row(outer,"Modelo L2/L3 (deployment-candidate.json)",self.model)
            self.file_row(outer,"Pasta dos resultados",self.dest,True)
            self.file_row(outer,"Referência B1 do banco (opcional)",self.ref)
            self.file_row(outer,"Perfil S4 efetivo (opcional)",self.controls)
            for label,var,width in (("Cenário",self.scenario,22),("Duração s",self.seconds,6),("Mapa Hz",self.map_hz,5),("OCR Hz",self.reader_hz,5),("Amostra Hz",self.sample_hz,5)):
                ttk.Label(line,text=label).pack(side="left");ttk.Entry(line,textvariable=var,width=width).pack(side="left",padx=4)
            ttk.Button(line,text="INICIAR MAPEAMENTO",command=self.start).pack(side="left",padx=8)
            ttk.Button(line,text="Encerrar e salvar",command=self.stop).pack(side="left")
        self.status=ttk.Label(outer,text=("Escolha um monitor/janela. A seleção ainda não inicia captura." if self.hm4 else "A seleção não inicia captura. Escolha a fonte, modelo e destino."));self.status.pack(anchor="w",pady=5)
        if self.hm4:
            coach=tk.Frame(outer,bg="#241746",padx=18,pady=10)
            coach.pack(fill="x",pady=(2,8))
            self.coach_header=tk.Label(coach,text="AGENTE  /  ORIENTAÇÃO EM TEMPO REAL",
                                       bg="#241746",fg="#bda8ff",font=("Segoe UI",9,"bold"),anchor="w")
            self.coach_header.pack(fill="x")
            self.tip_label=tk.Label(coach,text="Aguardando captura e leituras confiáveis.",
                                    bg="#241746",fg="#ffffff",font=("Segoe UI",15,"bold"),
                                    anchor="w",justify="left",wraplength=1300)
            self.tip_label.pack(fill="x",pady=(4,2))
            self.coach_meta=tk.Label(coach,text="As leituras mostram fatos; ações exigem evidência suficiente.",
                                     bg="#241746",fg="#c9bde8",font=("Segoe UI",9),anchor="w")
            self.coach_meta.pack(fill="x")
            coach.bind("<Configure>",lambda event:self.tip_label.configure(wraplength=max(300,event.width-36)))
        tabs=ttk.Notebook(outer);tabs.pack(fill="both",expand=True)
        mapping=ttk.Frame(tabs);performance=ttk.Frame(tabs);data=ttk.Frame(tabs)
        tabs.add(mapping,text="HUD ao vivo / geometria");tabs.add(performance,text="Performance");tabs.add(data,text="Dados coletados")
        if self.hm4:
            history=ttk.Frame(tabs);tabs.add(history,text="Histórico de orientações")
            self.tip_log=tk.Text(history,bg="#ffffff",fg="#252045",wrap="word",font=("Segoe UI",11),state="disabled")
            self.tip_log.pack(fill="both",expand=True,padx=8,pady=8)
        bar=ttk.Frame(mapping);bar.pack(fill="x")
        for label,value in (("Captura bruta","capture"),("Mapa neural + geometria","map"),("Leituras / OCR","reader"),("Tabuleiro / itens","hub")):
            ttk.Radiobutton(bar,text=label,variable=self.which,value=value,command=self.repaint).pack(side="left",padx=3)
        ttk.Checkbutton(bar,text="Overlays",variable=self.overlays,command=self.repaint).pack(side="left",padx=8)
        ttk.Button(bar,text="Congelar inspeção",command=self.toggle_freeze).pack(side="right")
        self.caption=ttk.Label(mapping,text="A imagem, os recortes e as caixas exibidos pertencem ao mesmo frame_id.");self.caption.pack(anchor="w")
        split=ttk.Panedwindow(mapping,orient="horizontal");split.pack(fill="both",expand=True)
        left=ttk.Frame(split);right=ttk.Frame(split);split.add(left,weight=3);split.add(right,weight=2)
        self.canvas=tk.Canvas(left,bg="#e6def9" if self.hm4 else "#060c10",highlightthickness=0,width=900,height=520);self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",lambda _ : self.repaint())
        right.columnconfigure(0,weight=1);right.rowconfigure(0,weight=1)
        self.table=ttk.Treeview(right,columns=("region","status","value"),show="headings",height=5)
        for c,w in (("region",170),("status",185),("value",100)):self.table.heading(c,text=c);self.table.column(c,width=w,minwidth=60)
        self.table.grid(row=0,column=0,sticky="nsew");self.table.bind("<<TreeviewSelect>>",self.selected)
        scroll=ttk.Scrollbar(right,orient="vertical",command=self.table.yview);scroll.grid(row=0,column=1,sticky="ns");self.table.configure(yscrollcommand=scroll.set)
        ttk.Label(right,text="Clique numa região para ver o recorte original e toda a proveniência.",wraplength=430).grid(row=1,column=0,columnspan=2,sticky="ew")
        self.crop_label=ttk.Label(right,anchor="center");self.crop_label.grid(row=2,column=0,columnspan=2,sticky="ew")
        self.details=tk.Text(right,height=6,bg="#ffffff" if self.hm4 else "#172934",fg="#252045" if self.hm4 else "#dce7ef",wrap="word");self.details.grid(row=3,column=0,columnspan=2,sticky="ew")
        self.perf=tk.Text(performance,bg="#ffffff" if self.hm4 else "#172934",fg="#252045" if self.hm4 else "#dce7ef",wrap="word");self.perf.pack(fill="both",expand=True)
        ttk.Label(data,text="O hot path trabalha em memória. PNGs/recortes são amostras assíncronas e limitadas; previsões não viram ground truth.",justify="left").pack(anchor="w",pady=10)
        self.data_text=tk.Text(data,height=18,bg="#ffffff" if self.hm4 else "#172934",fg="#252045" if self.hm4 else "#dce7ef",wrap="word");self.data_text.pack(fill="both",expand=True)
        ttk.Button(data,text="Abrir última sessão",command=self.open_output).pack(anchor="w",pady=5)
        root.protocol("WM_DELETE_WINDOW",self.close);root.after(30,self.tick)

    def render_hero(self,_=None):
        if not self.hm4:return
        from PIL import Image, ImageTk, ImageOps
        width=max(1,self.hero.winfo_width());height=max(1,self.hero.winfo_height())
        self.hero.delete("all")
        if self.hero_source:
            art=ImageOps.fit(self.hero_source,(width,height),Image.Resampling.LANCZOS,centering=(0.5,0.46))
            self.hero_photo=ImageTk.PhotoImage(art)
            self.hero.create_image(0,0,image=self.hero_photo,anchor="nw")
        self.hero.create_text(34,48,text="A G E N T E   T F T",anchor="w",font=("Segoe UI",27,"bold"),fill="#262047")
        self.hero.create_text(36,89,text="R E V I S Ã O   D E   R E P L A Y",anchor="w",font=("Segoe UI",11,"bold"),fill="#6545b4")
        self.hero.create_text(36,118,text="Assista ao vídeo, confira as evidências e meça o atraso das dicas.",anchor="w",font=("Segoe UI",10),fill="#40375e")
        self.hero.create_line(36,145,280,145,fill="#896bd0",width=2)

    def file_row(self,parent,label,var,directory=False):
        from tkinter import ttk,filedialog
        row=ttk.Frame(parent);row.pack(fill="x",pady=2);ttk.Label(row,text=label,width=35).pack(side="left")
        ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True)
        def choose():
            p=filedialog.askdirectory() if directory else filedialog.askopenfilename()
            if p:var.set(p)
        ttk.Button(row,text="Escolher",command=choose).pack(side="right")

    def active(self):return bool(self.session and not self.session.finished and not self.finalizing)

    def choose_source(self,tft_only=False):
        import tkinter as tk
        from tkinter import ttk,messagebox
        if self.active():messagebox.showinfo("Fonte","Encerre a sessão antes de mudar a fonte.");return
        dialog=tk.Toplevel(self.root);dialog.title("Fonte da HUD — captura Rust");dialog.geometry("980x520");dialog.transient(self.root)
        ttk.Label(dialog,text="Selecione explicitamente um monitor ou janela. A indicação TFT é apenas pelo título visível.",wraplength=920).pack(padx=12,pady=10)
        tree=ttk.Treeview(dialog,columns=("kind","label","pos"),show="headings",selectmode="browse")
        for c,t,w in (("kind","Tipo",90),("label","Monitor / janela / adaptador",700),("pos","Posição",140)):tree.heading(c,text=t);tree.column(c,width=w,minwidth=70)
        tree.pack(fill="both",expand=True,padx=12);status=ttk.Label(dialog,text="Enumerando…");status.pack(pady=6)
        result=queue.Queue(maxsize=1);choices={}
        def load():
            try:result.put((list_targets(runtime_paths()["configs"]),None))
            except Exception as exc:result.put((None,str(exc)))
        threading.Thread(target=load,daemon=True).start()
        def poll():
            if not dialog.winfo_exists():return
            try:rows,error=result.get_nowait()
            except queue.Empty:dialog.after(40,poll);return
            if error:status.configure(text=error);return
            shown=[r for r in rows if not tft_only or r.get("candidate_tft")]
            for i,r in enumerate(shown):
                choices[str(i)]=r;tree.insert("","end",iid=str(i),values=(r["kind"],target_label(r),str(r["bounds"][:2])))
            hints=[str(i) for i,r in enumerate(shown) if r.get("candidate_tft")]
            if hints:tree.selection_set(hints[0]);tree.see(hints[0])
            status.configure(text=f"{len(shown)} fontes. Nenhuma captura começou.")
        def accept():
            if not tree.selection():return
            self.selection=dict(choices[tree.selection()[0]]);self.source_label.configure(text=target_label(self.selection));dialog.destroy()
        ttk.Button(dialog,text="Usar fonte selecionada",command=accept).pack(pady=8);dialog.after(40,poll)

    def start(self):
        from tkinter import messagebox
        if self.active() or self.finalizing:return
        try:
            if not self.selection:raise ValueError("Escolha monitor ou janela.")
            if not self.hm4 and not self.model.get():raise ValueError("Selecione deployment-candidate.json.")
            if not self.dest.get():raise ValueError("Escolha pasta de resultados.")
            if self.hm4 and not self.model.get():self.model.set(discover_model())
            message=target_label(self.selection)+"\n\nAutoriza registrar imagens desta fonte para mapear a HUD?\n"
            if self.hm4 and self.replay_review.get():
                message += "Confirme que a fonte exibirá um vídeo de partida já encerrada. As dicas de revisão usam apenas leituras observadas."
            else:
                message += "Nenhum áudio, tecla, input automation ou dica estratégica é executado."
            if not messagebox.askyesno("Confirmar captura",message):return
            prefix="hm4" if self.hm4 else "hm3"
            output=self.smoke_output or str(Path(self.dest.get())/(prefix+"-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")))
            uri=f'capture://{self.selection["kind"]}/{self.selection["id"]}'
            p=runtime_paths()
            cls=HM4RuntimeSession if self.hm4 else RuntimeSession
            selected_model=self.model.get() if (not self.hm4 or self.replay_review.get()) else ""
            self.session=cls(Options(**p,video=uri,model=selected_model,output=output,
                seconds=float(self.seconds.get()),map_hz=float(self.map_hz.get()),reader_hz=float(self.reader_hz.get()),
                sample_hz=0.2 if self.vm_core else float(self.sample_hz.get()),
                scenario=self.scenario.get(),controls=self.controls.get() or None,
                board_reference=self.ref.get() or None,dataset_only=self.hm4 and not bool(selected_model),
                replay_review=self.hm4 and self.replay_review.get(),
                board_hub_enabled=self.hm4 and self.replay_review.get(),
                vm_core=self.vm_core,preview_hz=30,
                preview_width=max(160,min(1280,self.canvas.winfo_width()-8)),
                preview_height=max(90,min(720,self.canvas.winfo_height()-8)),
                max_samples=90 if self.vm_core else 600,
                max_bytes=384*1024**2 if self.vm_core else 1024**3,
                capture_consent=True,capture_expected=self.selection)).start()
            self.last={};self.current=None;self.freeze=False;self._table_key=None
            self.render_ms.clear();self.preview_times.clear();self._next_metrics_ns=0;self._next_preview_ns=0
        except Exception as exc:messagebox.showerror("HM4" if self.hm4 else "HM3",str(exc))

    def stop(self):
        if self.session and not self.session.done.is_set():self.session.request_stop()
    def test_voice(self):
        if not self.voice.voices:
            self.status.configure(text="Este pacote não contém vozes locais. Use o instalador HM4.5 com vozes.")
            return
        self.voice_enabled.set(True)
        self.voice.set_enabled(True)
        self.voice.say("Agente TFT pronto para a revisão.",0,force=True)
    def choose_voice(self,event=None):
        selected=self.voice_choice.get()
        for voice_id,label in self.voice.voices.items():
            if label==selected:
                self.voice.set_voice(voice_id)
                return
    def calibrate_board(self):
        from tkinter import messagebox
        try:
            if not self.session or not isinstance(self.session,HM4RuntimeSession):
                raise ValueError("Inicie uma revisão de replay antes de calibrar.")
            self.session.request_board_reference()
            self.status.configure(text="Calibração B1 solicitada. Deixe o tabuleiro do próprio jogador visível no vídeo.")
        except Exception as exc:messagebox.showerror("Calibrar tabuleiro",str(exc))
    def close(self):
        self.closing=True;self.stop()
        if self.voice:self.voice.close()
        if (not self.session or self.session.finished) and not self.finalizing:self.root.destroy()
    def toggle_freeze(self):self.freeze=not self.freeze;self.repaint()

    def _shown_regions(self,item):
        view=item.get("view_kind")
        regions=list(item["record"].get("regions") or [])
        if view=="map" and self.session and self.session.registry:
            regions=self.session.registry.fixed(item["frame"].width,item["frame"].height)+regions
        return regions

    def repaint(self):
        item=self.current if self.freeze and self.current else self.last.get(self.which.get())
        if not item:return
        from PIL import Image,ImageTk,ImageDraw
        started=time.perf_counter_ns()
        previous=self.current;self.current=item;f=item["frame"];view=item.get("view_kind");regions=self._shown_regions(item)
        if (previous is None or previous.get("view_kind")!=view or
                (view!="capture" and previous["frame"].id!=f.id)):
            self.crop_label.configure(image="",text="Selecione uma região.");self.details.delete("1.0","end")
        im=Image.frombytes("RGB",(f.width,f.height),f.rgb)
        w=max(100,self.canvas.winfo_width()-8);h=max(100,self.canvas.winfo_height()-8)
        if self.vm_core:
            w=min(w,1280);h=min(h,720)
            im.thumbnail((w,h),Image.Resampling.BILINEAR)
            scale_x=im.width/f.width;scale_y=im.height/f.height
        else:
            scale_x=scale_y=1.0
        if self.overlays.get() and view!="capture":
            draw=ImageDraw.Draw(im)
            for reg in regions:
                for cell in reg.get("guide_points",[]):
                    x,y=cell["screen"];x*=scale_x;y*=scale_y
                    draw.ellipse((x-4,y-4,x+4,y+4),outline="#bb91ff",width=2)
                b=reg.get("box")
                if not b or not valid_box(b,f.width,f.height):continue
                status=str(reg.get("status"))
                if str(reg["id"]).startswith("neural."):color="#ffca55"
                elif status in ("observed","accepted","coarse_candidate","offer_text_readable"):color="#57df93"
                elif "incompatible" in status or status in ("unknown","unavailable"):color="#ff6868"
                else:color="#5ad7dc"
                box=(b[0]*scale_x,b[1]*scale_y,b[2]*scale_x,b[3]*scale_y)
                draw.rectangle(box,outline=color,width=2)
                draw.text((box[0]+2,max(0,box[1]-13)),reg["id"],fill=color)
        if not self.vm_core:im.thumbnail((w,h),Image.Resampling.BILINEAR)
        if self.photo is not None and self.photo_size==im.size:
            self.photo.paste(im)
        else:
            self.photo=ImageTk.PhotoImage(im);self.photo_size=im.size
        center=(self.canvas.winfo_width()//2,self.canvas.winfo_height()//2)
        if self.canvas_image is None:
            self.canvas_image=self.canvas.create_image(*center,image=self.photo,anchor="center")
        else:
            self.canvas.itemconfigure(self.canvas_image,image=self.photo)
            self.canvas.coords(self.canvas_image,*center)
        source="CAPTURA";cap=getattr(f,"capture",None)
        age=(time.perf_counter_ns()-f.due_ns)/1e6
        physical = f'{cap["source_width"]}×{cap["source_height"]} original · ' if cap and cap.get('type')=='preview' else ''
        self.caption.configure(text=f'{"INSPEÇÃO CONGELADA · " if self.freeze else ""}{source} frame {f.id} · +{f.pts_ms/1000:.3f}s · {physical}{f.width}×{f.height} · idade {age:.1f} ms · geometria {f.epoch}')
        table_key=(view,None if view=="capture" else f.id)
        if table_key!=self._table_key:
            self._table_key=table_key
            self.table.delete(*self.table.get_children());self.row_data={}
            for i,reg in enumerate(regions):
                rid=str(i);self.row_data[rid]=reg;value=reg.get("value")
                self.table.insert("","end",iid=rid,values=(reg["id"],reg.get("status"),"" if value is None else str(value)[:90]))
        self.displayed+=1
        if self.vm_core:
            elapsed=(time.perf_counter_ns()-started)/1e6
            self.render_ms.append(elapsed)
            if view=="capture":
                self.preview_times.append(time.perf_counter_ns())
                if self.session and (self.displayed%20)==0:
                    self.session.store.emit('telemetry',dict(event='preview_render',frame_id=f.id,
                        render_ms=elapsed,source_age_ms=(time.perf_counter_ns()-f.due_ns)/1e6,
                        preview_size=[im.width,im.height],source_size=[f.width,f.height]))

    def selected(self,_=None):
        if not self.current or not self.table.selection():return
        from PIL import Image,ImageTk
        reg=self.row_data[self.table.selection()[0]];f=self.current["frame"];b=reg.get("box")
        self.details.delete("1.0","end");self.details.insert("end",json.dumps(reg,ensure_ascii=False,indent=2))
        if b and valid_box(b,f.width,f.height):
            im=Image.frombytes("RGB",(f.width,f.height),f.rgb).crop(crop_box(b,f.width,f.height))
            if im.width<100:im=im.resize((im.width*3,im.height*3),Image.Resampling.NEAREST)
            im.thumbnail((460,145),Image.Resampling.BILINEAR);self.zoom_photo=ImageTk.PhotoImage(im);self.crop_label.configure(image=self.zoom_photo,text="")
        else:self.crop_label.configure(image="",text="Sem retângulo observado/válido.")

    def _performance(self,s):
        with s.lock:traces=list(s.traces[-240:])
        maps=[x for x in traces if x["kind"]=="map"];reads=[x for x in traces if x["kind"]=="reader"];hps=[x for x in traces if x["kind"]=="hp"]
        hubs=[x for x in traces if x["kind"]=="hub"]
        stages={}
        for r in reads:
            for st in r.get("spans",[]):stages.setdefault(st["stage"],[]).append(st["duration_ms"])
        cap=None
        raw=self.last.get("capture")
        if raw:cap=getattr(raw["frame"],"capture",None)
        preview_fps=None
        if len(self.preview_times)>1:
            span=(self.preview_times[-1]-self.preview_times[0])/1e9
            if span>0:preview_fps=round((len(self.preview_times)-1)/span,1)
        transports={}
        for name,group in (("map",maps),("reader",reads),("hp",hps),("hub",hubs)):
            rows=[x["vm_transport"] for x in group if x.get("vm_transport")]
            if rows:
                transports[name]=dict(n=len(rows),encode_p95_ms=pct([x.get("encode_ms",0) for x in rows],.95),
                    roundtrip_p95_ms=pct([x["roundtrip_ms"] for x in rows],.95),
                    core_p95_ms=pct([x["core_ms"] for x in rows],.95),
                    wire_p95_bytes=pct([x["wire_bytes"] for x in rows],.95))
        return dict(
          source_frames=s.counts["source_frames"],mapped=s.counts["mapped_frames"],reader_results=s.counts["read_frames"],
          reader_native_runs=s.counts["reader_native_runs"],reader_exact_cache_hits=s.counts["reader_exact_cache_hits"],
          resolution_skipped=s.counts["reader_resolution_skipped"],
          queues=dict(map_replaced=s.map_pending.replaced,reader_replaced=s.native_pending.replaced,hp_replaced=s.hp_pending.replaced,preview_replaced=s.preview.replaced),
          neural=dict(inference_p50_ms=pct([x["inference_ms"] for x in maps],.5),inference_p95_ms=pct([x["inference_ms"] for x in maps],.95),
                      source_to_map_p95_ms=pct([x["total_ms"] for x in maps],.95)),
          readers=dict(source_to_reader_p50_ms=pct([x["total_ms"] for x in reads],.5),source_to_reader_p95_ms=pct([x["total_ms"] for x in reads],.95),
                       stages={k:dict(p50_ms=pct(v,.5),p95_ms=pct(v,.95),n=len(v)) for k,v in stages.items()}),
          hp=dict(results=s.counts["hp_results"],native_runs=s.counts["hp_native_runs"],source_to_hp_p50_ms=pct([x["total_ms"] for x in hps],.5),
                  source_to_hp_p95_ms=pct([x["total_ms"] for x in hps],.95),native_p50_ms=pct([x["native_ms"] for x in hps],.5),
                  native_p95_ms=pct([x["native_ms"] for x in hps],.95)),
          hub=dict(results=s.counts["hub_results"],queue_replaced=s.hub_pending.replaced,
                   source_to_result_p50_ms=pct([x["total_ms"] for x in hubs],.5),
                   source_to_result_p95_ms=pct([x["total_ms"] for x in hubs],.95),
                   processing_p95_ms=pct([x["processing_ms"] for x in hubs],.95),
                   board_reference_status=s.versions.get("board_reference_status")),
          tips=dict(actionable=s.counts["replay_tips"],coach_updates=s.counts["coach_updates"],
                    mode="replay_review_only" if s.options.replay_review else "disabled"),
          capture=cap,vm_transport=transports,preview=dict(fps=preview_fps,
                                   capture_device_kind=(getattr(s.source,'ready',None) or {}).get('device_kind'),
                                   native_received=getattr(s.source,'preview_received',0),
                                   native_queue_replaced=getattr(getattr(s.source,'preview_frames',None),'replaced',0),
                                   render_p50_ms=pct(self.render_ms,.5),
                                   render_p95_ms=pct(self.render_ms,.95),max_size=[1280,720] if self.vm_core else None),
          samples_saved=s.store.counts["samples_saved"],write_queue_dropped=s.store.counts["write_queue_dropped"],
          voice=dict(enabled=bool(self.voice and self.voice.enabled),
                     selected=self.voice.voice_id if self.voice else None,
                     synthesis_ms=self.voice.last_generation_ms if self.voice else None,
                     error=self.voice.error if self.voice else None))

    def tick(self):
        s=self.session
        if s and not s.finished and not self.finalizing:
            try:
                f=s.preview.get(.001);self.last["capture"]=dict(frame=f,record=dict(regions=[]),ready_ns=f.ready_ns,view_kind="capture")
                now=time.perf_counter_ns()
                if not self.freeze and self.which.get()=="capture" and now>=self._next_preview_ns:
                    self.repaint();self._next_preview_ns=now+int(1e9/(s.options.preview_hz if self.vm_core else 30))
            except queue.Empty:pass
            for name,q in (("map",s.map_results),("reader",s.native_results),("hub",s.hub_results)):
                try:
                    item=q.get(.001);item["view_kind"]=name;self.last[name]=item
                    if not self.freeze and self.which.get()==name:self.repaint();s.acknowledge(item,name)
                except queue.Empty:pass
            tip=getattr(s,"latest_replay_tip",None)
            if tip:
                key=(tip.get("frame_id"),tip.get("text"))
                if key!=getattr(self,"_shown_tip_key",None):
                    self._shown_tip_key=key
                    age=(time.perf_counter_ns()-tip["source_due_ns"])/1e6
                    label='DICA' if tip.get('actionable') else 'LEITURA'
                    self.coach_header.configure(text=f'AGENTE  /  {label}',
                                                fg="#8cffbd" if tip.get('actionable') else "#bda8ff")
                    self.tip_label.configure(text=tip['text'])
                    self.coach_meta.configure(text=f'Frame {tip["frame_id"]} · atraso até a UI ~{age:.0f} ms · evidência: {", ".join(tip.get("basis") or []) or "insuficiente"}')
                    self.tip_history.appendleft(f'{label} · +{tip["source_ms"]/1000:.1f}s · atraso ~{age:.0f} ms\n{tip["text"]}\n')
                    self.tip_log.configure(state='normal');self.tip_log.delete('1.0','end')
                    self.tip_log.insert('1.0','\n'.join(self.tip_history));self.tip_log.configure(state='disabled')
                    if self.voice and tip.get('speech_text'):
                        self.voice.say(tip['speech_text'],age)
                    s.store.emit('telemetry',dict(event='coach_ui_applied',frame_id=tip['frame_id'],
                        source_age_ms=age,ui_queue_ms=(time.perf_counter_ns()-tip['ready_ns'])/1e6,
                        physical_display_measured=False,tip_status=tip['status'],actionable=tip.get('actionable',False)))
                    with s.lock:
                        s.traces.append(dict(kind='tip_ui' if tip.get('actionable') else 'coach_ui',
                                             frame_id=tip['frame_id'],total_ms=age,
                                             physical_display_measured=False))
            now=time.perf_counter_ns()
            if not self.vm_core or now>=self._next_metrics_ns:
                self._next_metrics_ns=now+250_000_000
                perf=self._performance(s);self.perf.delete("1.0","end");self.perf.insert("end",json.dumps(perf,ensure_ascii=False,indent=2))
                self.data_text.delete("1.0","end");self.data_text.insert("end",json.dumps(dict(samples_saved=s.store.counts["samples_saved"],
                  sample_budget=s.store.max_samples,bytes_saved=s.store.bytes,write_queue_dropped=s.store.counts["write_queue_dropped"],
                  note="Treino não roda neste executável; use o trainer offline após revisar as amostras."),ensure_ascii=False,indent=2))
                self.status.configure(text=f'Mapeando HUD · captura {s.counts["source_frames"]} · OCR HUD/loja {s.counts["reader_native_runs"]} · HUB {s.counts["hub_results"]} · leituras {s.counts["coach_updates"]} · dicas {s.counts["replay_tips"]} · HP {s.counts["hp_results"]} · PNG {s.store.counts["samples_saved"]}')
            if s.done.is_set() and s.map_results.empty() and s.native_results.empty() and s.hub_results.empty():
                self.finalizing=True;self.status.configure(text="Selando telemetria e amostras…")
                def finish():
                    try:self.final_result=s.finish()
                    except Exception as exc:self.final_result=dict(execution_complete=False,error=str(exc))
                threading.Thread(target=finish,daemon=True).start()
        if self.finalizing and self.final_result is not None:
            result=self.final_result;self.final_result=None;self.finalizing=False;self.last_finished=s.options.output
            self.perf.delete("1.0","end");self.perf.insert("end",json.dumps(result,ensure_ascii=False,indent=2))
            label=("Concluído (encerrado pelo usuário)" if result.get("stopped_by_user") else "Concluído") if result.get("execution_complete") else "Parcial: "+str(result.get("error"))
            self.status.configure(text=label+" · "+self.last_finished)
            if self.smoke or self.closing:self.root.destroy();return
        elif self.closing and (not s or s.finished) and not self.finalizing:self.root.destroy();return
        self.root.after(10 if self.vm_core else 30,self.tick)

    def open_output(self):
        if not self.last_finished:return
        if os.name=="nt":os.startfile(self.last_finished)

def main(mode="hm3"):
    hm4=mode=="hm4"
    p=argparse.ArgumentParser(description="Agente TFT "+("HM4 Auto" if hm4 else "HM3 — HUD-first, captura nativa somente"))
    p.add_argument("--capture");p.add_argument("--capture-consent",action="store_true");p.add_argument("--headless",action="store_true")
    p.add_argument("--ui-smoke",action="store_true");p.add_argument("--model");p.add_argument("--output");p.add_argument("--seconds",type=float,default=5)
    p.add_argument("--replay-review",action="store_true")
    p.add_argument("--voice-smoke-output")
    p.add_argument("--map-hz",type=float,default=8);p.add_argument("--reader-hz",type=float,default=2 if mode=="hm4" else 1);p.add_argument("--sample-hz",type=float,default=1)
    a=p.parse_args()
    if a.voice_smoke_output:
        if not hm4:p.error("Voice smoke is HM4 only")
        from .voice import _synthesize, available_voices, voice_assets
        import io, wave
        voices=available_voices()
        if set(voices)!={'dii','cadu','faber'}:raise RuntimeError('Pacote de vozes incompleto')
        checks={}
        for voice_id in voices:
            wav,_=_synthesize('Compre a unidade agora.',voice_id,voice_assets())
            with wave.open(io.BytesIO(wav),'rb') as audio:
                checks[voice_id]=dict(bytes=len(wav),rate=audio.getframerate(),frames=audio.getnframes())
                if audio.getnframes()==0:raise RuntimeError('Voz vazia: '+voice_id)
        Path(a.voice_smoke_output).write_text(json.dumps(checks),encoding='utf-8')
        return
    if a.headless or a.ui_smoke:
        required=all((a.capture,a.capture_consent,a.output)) and (hm4 or bool(a.model))
        if not required:p.error("capture, consent, output"+("" if hm4 else ", model")+" são obrigatórios")
        kind,identity=__import__("hm.capture_source",fromlist=["capture_target"]).capture_target(a.capture)
        selected=next((r for r in list_targets(runtime_paths()["configs"]) if r["kind"]==kind and r["id"]==identity),None)
        if selected is None:p.error("Fonte não disponível")
        if a.headless:
            cls=HM4RuntimeSession if hm4 else RuntimeSession
            o=Options(**runtime_paths(),video=a.capture,model=a.model or "",output=a.output,seconds=a.seconds,map_hz=a.map_hz,
                      reader_hz=a.reader_hz,sample_hz=a.sample_hz,capture_consent=True,capture_expected=selected,
                      replay_review=hm4 and a.replay_review,board_hub_enabled=hm4 and a.replay_review,
                      dataset_only=hm4 and not bool(a.model),scenario="hm4-ci" if hm4 else "hm3-ci")
            sess=cls(o).start()
            while not sess.done.is_set():
                for q in (sess.map_results,sess.native_results,sess.hub_results):
                    try:q.get(.005)
                    except queue.Empty:pass
                time.sleep(.01)
            result=sess.finish();print(("HM4_SUMMARY=" if hm4 else "HM3_SUMMARY=")+json.dumps(result,ensure_ascii=False));return 0 if result["execution_complete"] else 2
        import tkinter as tk
        root=tk.Tk();app=App(root,mode);app.selection=selected;app.source_label.configure(text=target_label(selected))
        if a.model:app.model.set(a.model)
        if a.replay_review:app.replay_review.set(True)
        app.dest.set(str(Path(a.output).parent));app.seconds.set(str(a.seconds));app.smoke_output=a.output;app.smoke=True
        from tkinter import messagebox
        old=messagebox.askyesno;messagebox.askyesno=lambda *x,**k: True
        root.after(100,app.start);root.mainloop();messagebox.askyesno=old
        return 0 if app.session and app.session.finished and not app.session.error and app.displayed else 2
    import tkinter as tk
    root=tk.Tk();App(root,mode);root.mainloop();return 0
