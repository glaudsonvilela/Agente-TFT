"""Interactive Portuguese setup assistant launched by the HM4.5 Inno installer."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from hm45_setup_core import CoreInstaller, SetupError, restart_windows, wait_wsl_after_restart, wsl_available


INK = "#261c4d"
PURPLE = "#6751a6"
PALE = "#f4f1ff"
WHITE = "#ffffff"


class SetupWindow:
    def __init__(self, app_exe: Path, resume: bool = False, resume_headless: bool = False):
        self.app_exe = app_exe
        self.resume = resume
        self.resume_headless = resume_headless
        self.log_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgenteTFT-HM45" / "setup.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.installer: CoreInstaller | None = None
        self.preflight_ready = False
        self.vm_ready = False
        self.restart_pending = False
        self.headless_selected = False
        self.busy = False
        self.step = 0
        self.root = tk.Tk()
        self.headless_wsl = tk.BooleanVar(master=self.root, value=False)
        self.root.title("Agente TFT · Instalação guiada")
        self.root.geometry("860x600")
        self.root.minsize(760, 540)
        self.root.configure(bg=PALE)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._layout()
        if resume:
            self._show(1)
            self.root.after(150, lambda: self._start("install", self._install))
        else:
            self._show(0)
            self.root.after(150, lambda: self._start("preflight", self._preflight))
        self.root.after(100, self._drain)

    def _layout(self):
        rail = tk.Frame(self.root, bg=INK, width=218)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Label(rail, text="✦  AGENTE TFT", fg=WHITE, bg=INK,
                 font=("Segoe UI", 17, "bold"), anchor="w").pack(fill="x", padx=20, pady=(30, 34))
        self.step_labels = []
        for number, title in enumerate(("Verificação", "Instalação", "Concluir"), 1):
            label = tk.Label(rail, text=f"{number:02d}   {title}", fg="#beb5d9", bg=INK,
                             font=("Segoe UI", 11), anchor="w", padx=20, pady=12)
            label.pack(fill="x")
            self.step_labels.append(label)
        tk.Label(rail, text="LABORATÓRIO HM4.5\nWindows + VM WSL 2", fg="#a69bc9", bg=INK,
                 font=("Segoe UI", 9), justify="left", anchor="sw").pack(side="bottom", fill="x", padx=20, pady=25)

        body = tk.Frame(self.root, bg=PALE)
        body.pack(side="left", fill="both", expand=True)
        self.kicker = tk.Label(body, fg=PURPLE, bg=PALE, font=("Segoe UI", 10, "bold"), anchor="w")
        self.kicker.pack(fill="x", padx=38, pady=(34, 7))
        self.heading = tk.Label(body, fg=INK, bg=PALE, font=("Segoe UI", 23, "bold"), anchor="w")
        self.heading.pack(fill="x", padx=38)
        self.description = tk.Label(body, fg="#514b67", bg=PALE, font=("Segoe UI", 11),
                                    justify="left", anchor="nw", wraplength=540)
        self.description.pack(fill="x", padx=38, pady=(15, 18))
        self.details = tk.Text(body, height=12, fg=INK, bg=WHITE, font=("Segoe UI", 10),
                               bd=0, padx=18, pady=15, wrap="word", state="disabled")
        self.details.pack(fill="both", expand=True, padx=38, pady=(0, 20))
        self.headless_slot = tk.Frame(body, bg=PALE)
        self.headless_slot.pack(fill="x", padx=38, pady=(0, 10))
        self.headless_option = tk.Checkbutton(
            self.headless_slot, variable=self.headless_wsl, bg=PALE, fg=INK, activebackground=PALE,
            anchor="w", justify="left", wraplength=530,
            text="VM sem WSLg: evita as janelas Remote Desktop/RemoteApp. Desativa aplicativos gráficos em todas as distribuições WSL após reiniciar.")
        self.headless_option.pack(fill="x")
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        buttons = tk.Frame(body, bg=PALE)
        buttons.pack(fill="x", padx=38, pady=(0, 28))
        self.next = ttk.Button(buttons, text="Continuar", command=self._next)
        self.next.pack(side="right")
        self.secondary = ttk.Button(buttons, text="", command=self._secondary)

    def _text(self, value: str, append: bool = False):
        self.details.configure(state="normal")
        if not append:
            self.details.delete("1.0", "end")
        self.details.insert("end", value + ("\n" if value and not value.endswith("\n") else ""))
        self.details.see("end")
        self.details.configure(state="disabled")

    def _show(self, step: int):
        self.step = step
        self.next.configure(command=self._next)
        for i, label in enumerate(self.step_labels):
            label.configure(bg=PURPLE if i == step else INK, fg=WHITE if i == step else "#beb5d9")
        self.secondary.pack_forget()
        if step == 0:
            self.headless_option.pack(fill="x")
        else:
            self.headless_option.pack_forget()
        pages = (
            ("PASSO 1 DE 3", "Verificando o computador",
             "Vamos conferir o Windows, o WSL 2 e o pacote da VM automaticamente.",
             "A captura Rust e a prévia de até 720p ficam no Windows. A VM recebe quadros RGB pela conexão IP local somente quando precisa analisar.\n\n"
             "O vídeo permanece no seu player. Se o WSL 2 precisar ser habilitado, o Windows pedirá permissão e talvez um reinício."),
            ("PASSO 2 DE 3", "Instalando e testando a VM",
             "Aguarde a importação. O Agente TFT só será marcado como pronto depois do teste completo de saúde.",
             "Preparando a instalação…"),
            ("PASSO 3 DE 3", "Tudo pronto",
             "A VM passou nos testes de versão, modelos, catálogo e conexão local.",
             "Abra o Agente TFT pelo botão abaixo ou pelo novo ícone da área de trabalho."),
        )
        kicker, heading, description, details = pages[step]
        self.kicker.configure(text=kicker)
        self.heading.configure(text=heading)
        self.description.configure(text=description)
        self._text(details)
        labels = ("Instalar VM", "Aguarde…", "Abrir Agente TFT")
        self.next.configure(text=labels[step], state="normal" if step == 2 or
                            (step == 0 and self.preflight_ready) else "disabled")
        if step == 2:
            self.secondary.configure(text="Fechar", command=self._close)
            self.secondary.pack(side="right", padx=(0, 12))

    def _next(self):
        if self.busy:
            return
        if self.step == 0 and self.preflight_ready:
            self.headless_selected = self.headless_wsl.get()
            if self.headless_selected and not messagebox.askyesno(
                "WSL sem interface gráfica",
                "O Agente TFT usa apenas IP local, mas o WSLg abre um cliente Remote Desktop em segundo plano. "
                "Desativar WSLg em todas as distribuições WSL deste usuário? Aplicativos Linux com janela deixarão de abrir "
                "até você restaurar .wslconfig. O assistente guardará uma cópia e pedirá reinício.", parent=self.root):
                return
            self._show(1)
            self._start("install", self._install)
        elif self.step == 2 and self.vm_ready:
            subprocess.Popen([str(self.app_exe)], cwd=str(self.app_exe.parent))
            self._close()

    def _restart(self):
        if not self.restart_pending or self.busy:
            return
        if not messagebox.askyesno("Reiniciar o Windows",
                                   "Salve seu trabalho antes de continuar. Reiniciar o Windows agora?",
                                   parent=self.root):
            return
        self._log("Usuário escolheu Reiniciar agora; retomada registrada em RunOnce.")
        try:
            restart_windows()
        except (OSError, SetupError) as exc:
            messagebox.showerror("Reinício não iniciado", str(exc), parent=self.root)

    def _secondary(self):
        self._close()

    def _start(self, name: str, fn):
        self.busy = True
        self.next.configure(state="disabled")
        self.secondary.pack_forget()
        self.progress.pack(fill="x", padx=38, pady=(0, 15))
        self.progress.start(12)

        def work():
            try:
                result = fn()
                self.events.put((name + ":ok", str(result)))
            except Exception as exc:
                self.events.put((name + ":error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _report(self, message: str):
        self._log(message)
        self.events.put(("log", message))

    def _log(self, message: str):
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")

    def _preflight(self):
        self.installer = self._make_installer()
        return self.installer.preflight(self._report).wsl_ready

    def _make_installer(self) -> CoreInstaller:
        return CoreInstaller(self.app_exe.parent / "core",
                             Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgenteTFT-Core", self.app_exe)

    def _install(self):
        if self.installer is None:
            self.installer = self._make_installer()
        if not self.preflight_ready:
            # A resumed session must recheck the package; the fresh session
            # already did this before the user pressed Install.
            self.installer.preflight(self._report)
        if self.resume and not self.resume_headless:
            wait_wsl_after_restart(self.installer.run, self._report)
        if not self.resume and self.headless_selected and not self.installer.use_headless_wsl(self._report):
            return "restart"
        if not wsl_available(self.installer.run):
            if not self.installer.enable_wsl(self._report):
                return "restart"
        return self.installer.install(self._report)

    def _drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._text(value, append=True)
                elif kind == "preflight:ok":
                    self.busy = False
                    self.progress.stop()
                    self.progress.pack_forget()
                    self.preflight_ready = True
                    self.next.configure(state="normal", text="Instalar VM", command=self._next)
                    self._text("Verificação concluída. Clique em Instalar VM.", append=True)
                elif kind == "install:ok":
                    self.busy = False
                    self.progress.stop()
                    self.progress.pack_forget()
                    if value == "restart":
                        self.restart_pending = True
                        self.heading.configure(text="Reinício necessário")
                        self.description.configure(text="O Windows precisa reiniciar para concluir o WSL 2. "
                                                       "O assistente continuará automaticamente no próximo login.")
                        self._text("Salve seu trabalho. Você pode reiniciar agora pelo botão ou mais tarde.", append=True)
                        self.next.configure(text="Reiniciar agora", state="normal", command=self._restart)
                        self.secondary.configure(text="Mais tarde", command=self._close)
                        self.secondary.pack(side="right", padx=(0, 12))
                    else:
                        self.vm_ready = True
                        self._show(2)
                elif kind.endswith(":error"):
                    self.busy = False
                    self.progress.stop()
                    self.progress.pack_forget()
                    self._log("ERRO: " + value)
                    self.heading.configure(text="Precisamos corrigir uma etapa")
                    self.description.configure(text=value)
                    self._text("Nenhuma outra distribuição WSL foi removida. Você pode tentar novamente.\n"
                               f"Log de instalação: {self.log_path}", append=True)
                    retry = self._preflight if kind.startswith("preflight") else self._install
                    self.next.configure(text="Tentar novamente", state="normal",
                                        command=lambda action=retry, label=kind.split(":", 1)[0]:
                                        self._start(label, action))
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _close(self):
        if self.busy:
            return
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0 if self.vm_ready else 1


def main() -> int:
    app_exe = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    if sys.platform != "win32":
        raise SetupError("O assistente de instalação requer Windows.")
    return SetupWindow(app_exe, resume="--resume-core" in sys.argv,
                       resume_headless="--resume-headless" in sys.argv).run()
