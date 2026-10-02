"""HM2 UI source selection on top of the existing HUD-first mapper.

Capturing is explicit and visible. TFT names are suggestions from window titles,
not account/process identity. E1 controlled tips remain a separate replay tool.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import argparse, json, queue, sys, threading, time
from .app import App, paths
from .session import Options, Session
from .capture_source import list_targets


def target_label(target):
    b = target['bounds']; size = f'{b[2]-b[0]} × {b[3]-b[1]}'
    if target['kind'] == 'monitor':
        return f"Monitor {target['device']} | {target['label']} | {size} | {target['adapter']}"
    hint = ' [possível TFT/LoL]' if target.get('candidate_tft') else ''
    return f"Janela: {target['label']}{hint} | {size}"


class CaptureApp(App):
    def __init__(self, root):
        super().__init__(root)
        import tkinter as tk
        self.capture_selection = None
        self.cli_consent = False
        self.capture_dialog = None
        root.title('Agente TFT — HUD Mapper HM2 / captura Rust')
        menu = tk.Menu(root); source = tk.Menu(menu, tearoff=0)
        source.add_command(label='Escolher monitor ou janela…', command=self.choose_source)
        source.add_command(label='Procurar janela TFT / League…', command=lambda:self.choose_source(True))
        source.add_command(label='Usar gravação encerrada…', command=self.choose_video)
        menu.add_cascade(label='Fonte de imagens', menu=source); root.configure(menu=menu)
        self.status.configure(text='HUD primeiro. Menu Fonte de imagens: monitor, janela ou vídeo. Captura somente após confirmar e iniciar.')
        def relabel(widget):
            try:
                if widget.cget('text') == 'Gravação local encerrada':widget.configure(text='Fonte: vídeo ou captura Rust selecionada')
            except tk.TclError:pass
            for child in widget.winfo_children():relabel(child)
        relabel(root)

    def active(self):
        return bool(self.session and not self.session.finished)

    def choose_video(self):
        from tkinter import filedialog, messagebox
        if self.active():
            messagebox.showinfo('Fonte','Encerre a sessão antes de mudar a fonte.');return
        p = filedialog.askopenfilename(title='Gravação encerrada',filetypes=[('Vídeos','*.mp4 *.mkv *.avi *.mov *.webm')])
        if p:self.video.set(p);self.capture_selection=None

    def choose_source(self, tft_only=False):
        import tkinter as tk
        from tkinter import ttk, messagebox
        if self.active():
            messagebox.showinfo('Fonte','Encerre a sessão antes de mudar monitor ou janela.');return
        if self.capture_dialog and self.capture_dialog.winfo_exists():self.capture_dialog.lift();return
        dialog=tk.Toplevel(self.root);self.capture_dialog=dialog;dialog.title('Escolher fonte de pixels — captura Rust')
        dialog.geometry('970x500');dialog.transient(self.root)
        ttk.Label(dialog,text='Escolha apenas o conteúdo que autoriza registrar. O título sugere TFT; não comprova identidade.',wraplength=920).pack(padx=12,pady=12)
        tree=ttk.Treeview(dialog,columns=('kind','label','size'),show='headings',selectmode='browse')
        for key,label,width in [('kind','Tipo',95),('label','Monitor / janela / adaptador',650),('size','Posição',140)]:
            tree.heading(key,text=label);tree.column(key,width=width,minwidth=70)
        tree.pack(fill='both',expand=True,padx=12)
        status=ttk.Label(dialog,text='Enumerando monitores e janelas visíveis…');status.pack(padx=12,pady=8)
        choices={};result=queue.Queue(maxsize=1)
        def lookup():
            try:result.put((list_targets(paths()['configs']),None))
            except Exception as exc:result.put((None,str(exc)))
        threading.Thread(target=lookup,daemon=True).start()
        def poll():
            if not dialog.winfo_exists():return
            try:rows,error=result.get_nowait()
            except queue.Empty:dialog.after(40,poll);return
            if error:status.configure(text=error);return
            shown=[r for r in rows if not tft_only or r.get('candidate_tft')]
            for i,r in enumerate(shown):
                choices[str(i)]=r
                tree.insert('','end',iid=str(i),values=(r['kind'],target_label(r),str(r['bounds'][:2])))
            hints=[str(i) for i,r in enumerate(shown) if r.get('candidate_tft')]
            if hints:tree.selection_set(hints[0]);tree.see(hints[0])
            status.configure(text=f'{len(shown)} fontes. A escolha ainda não inicia a captura.' if shown else 'Nenhuma janela candidata encontrada; use a lista de monitores/janelas.')
        def select():
            if not tree.selection():return
            r=dict(choices[tree.selection()[0]]);self.capture_selection=r
            self.video.set(f"capture://{r['kind']}/{r['id']}")
            self.status.configure(text='Fonte escolhida: '+target_label(r));dialog.destroy()
        ttk.Button(dialog,text='Usar fonte selecionada',command=select).pack(pady=10)
        dialog.after(40,poll)

    def start(self):
        if not self.video.get().startswith('capture://'):
            return super().start()
        from tkinter import messagebox
        if self.finalizing or self.active():return
        if self.training and self.training.poll() is None:
            messagebox.showerror('Captura','Encerre o treinamento antes de capturar.');return
        try:
            if not self.dest.get():raise ValueError('Escolha uma pasta gravável com espaço.')
            selection=self.capture_selection
            if not selection:raise ValueError('Escolha a fonte pelo menu; não use um identificador antigo.')
            consent=self.cli_consent or messagebox.askyesno('Confirmar captura visível',
                target_label(selection)+'\n\nAutoriza registrar imagens desta fonte para mapear o HUD?\n'
                'Monitores podem incluir notificações e outros aplicativos. Nenhum áudio ou tecla será registrado.\n'
                'Use SDR; HDR ainda não está validado. A borda de captura do Windows não será escondida.\n'
                'Isso não é uma garantia de aprovação da Riot/Vanguard. Não há dicas estratégicas ao vivo.')
            if not consent:return
            output=self.smoke_output or str(Path(self.dest.get())/('hud-capture-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
            self.session=Session(Options(**paths(),video=self.video.get(),model=self.model.get(),output=output,
                seconds=float(self.seconds.get()),scenario=self.scenario.get(),controls=self.controls.get() or None,
                board_reference=self.ref.get() or None,capture_consent=True,capture_expected=selection)).start()
            self.last={};self.freeze=False;self.current=None
        except Exception as exc:messagebox.showerror('HUD Mapper',str(exc))

    def engine_window(self):
        from tkinter import messagebox
        if self.active() and self.session.options.video.startswith('capture://'):
            messagebox.showinfo('Laboratório','Durante captura, prioridade é mapear e coletar o HUD.\nDicas do motor ficam separadas no laboratório de replay.');return
        return super().engine_window()


def main():
    if '--capture' not in sys.argv and len(sys.argv)>1:
        from .app import main as replay_main
        return replay_main()
    if '--capture' in sys.argv:
        p=argparse.ArgumentParser(description='HUD Mapper HM2 — captura explícita Rust/WGC')
        p.add_argument('--capture',required=True);p.add_argument('--capture-consent',action='store_true')
        p.add_argument('--headless',action='store_true');p.add_argument('--ui-smoke',action='store_true')
        p.add_argument('--model',required=True);p.add_argument('--output',required=True)
        p.add_argument('--seconds',type=float,default=300);p.add_argument('--board-reference');p.add_argument('--controls')
        a=p.parse_args()
        if not a.capture_consent:p.error('--capture-consent obrigatório')
        from .capture_source import capture_target
        kind,identity=capture_target(a.capture)
        selected=next((r for r in list_targets(paths()['configs']) if r['kind']==kind and r['id']==identity),None)
        if selected is None:p.error('Fonte não está disponível')
        if a.headless:
            s=Session(Options(**paths(),video=a.capture,model=a.model,output=a.output,seconds=a.seconds,
                capture_consent=True,capture_expected=selected,board_reference=a.board_reference,controls=a.controls)).start()
            try:
                while not s.done.is_set():
                    for q in (s.map_results,s.native_results):
                        try:q.get(.005)
                        except queue.Empty:pass
                    time.sleep(.02)
                summary=s.finish()
            except KeyboardInterrupt:
                s.stop();s.thread.join(35);summary=s.finish()
            print('HUD_MAPPER_SUMMARY='+json.dumps(summary,ensure_ascii=False))
            print('HUD_MAPPER_COMPARISON='+str(Path(a.output)/'comparison.txt'))
            return 0 if summary['execution_complete'] else 2
        import tkinter as tk
        root=tk.Tk();app=CaptureApp(root)
        app.capture_selection=selected;app.cli_consent=True
        app.video.set(a.capture);app.model.set(a.model);app.dest.set(str(Path(a.output).parent))
        app.seconds.set(str(a.seconds));app.smoke_output=a.output;app.smoke=a.ui_smoke
        root.after(100,app.start);root.mainloop()
        if a.ui_smoke:return 0 if app.session and app.session.finished and not app.session.error and app.displayed else 2
        return 0
    import tkinter as tk
    root=tk.Tk();CaptureApp(root);root.mainloop();return 0
