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
from tkinter import ttk

from hm45_setup_core import CoreInstaller, SetupError


INK = "#261c4d"
PURPLE = "#6751a6"
PALE = "#f4f1ff"
WHITE = "#ffffff"


class SetupWindow:
    def __init__(self, app_exe: Path, resume: bool = False):
        self.app_exe = app_exe
        self.log_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgenteTFT-HM45" / "setup.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.installer: CoreInstaller | None = None
        self.preflight_ready = False
        self.vm_ready = False
        self.busy = False
        self.step = 0
        self.root = tk.Tk()
        self.root.title("Agente TFT · Instalação guiada")
        self.root.geometry("860x600")
        self.root.minsize(760, 540)
        self.root.configure(bg=PALE)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._layout()
        if resume:
            self.installer = CoreInstaller(app_exe.parent / "core",
                                           Path(os.environ["LOCALAPPDATA"]) / "AgenteTFT-Core", app_exe)
            self._show(3)
            self.root.after(150, lambda: self._start("install", self._install))
        else:
            self._show(0)
        self.root.after(100, self._drain)

    def _layout(self):
        rail = tk.Frame(self.root, bg=INK, width=218)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Label(rail, text="✦  AGENTE TFT", fg=WHITE, bg=INK,
                 font=("Segoe UI", 17, "bold"), anchor="w").pack(fill="x", padx=20, pady=(30, 34))
        self.step_labels = []
        for number, title in enumerate(("Visão geral", "Seu computador", "Privacidade", "Instalação", "Concluir"), 1):
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
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        buttons = tk.Frame(body, bg=PALE)
        buttons.pack(fill="x", padx=38, pady=(0, 28))
        self.back = ttk.Button(buttons, text="Voltar", command=self._previous)
        self.back.pack(side="left")
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
        self.back.configure(state="normal" if 0 < step < 3 and not self.busy else "disabled")
        pages = (
            ("PASSO 1 DE 5", "Vamos preparar o Agente TFT",
             "O instalador já copiou o aplicativo. Agora vamos conferir seu PC e preparar a VM leve que processará a análise.",
             "Windows: captura de tela Rust e prévia de vídeo.\n"
             "VM WSL 2: análise de recortes, modelos e dicas.\n\n"
             "Se o Windows precisar habilitar o WSL 2, você verá a janela de permissão do sistema. "
             "Pode ser necessário reiniciar o computador; o assistente continuará no próximo login."),
            ("PASSO 2 DE 5", "Verificação do computador",
             "Vamos verificar Windows, memória, espaço, virtualização, WSL 2 e a integridade do pacote da VM.",
             "Clique em “Verificar meu PC”. Nenhuma configuração será alterada nesta etapa."),
            ("PASSO 3 DE 5", "Como os dados circulam",
             "A captura permanece no Windows. Só os recortes necessários seguem pela conexão IP local para a VM.",
             "A prévia 720p fica no Windows para evitar atraso.\n"
             "O instalador não envia a gravação para a internet.\n"
             "A VM não altera outras distribuições WSL nem a configuração global do WSL.\n\n"
             "Na próxima etapa, a instalação da VM começa. O Windows pode solicitar permissão de administrador."),
            ("PASSO 4 DE 5", "Instalando e testando a VM",
             "Aguarde a importação. O Agente TFT só será marcado como pronto depois do teste completo de saúde.",
             "Preparando a instalação…"),
            ("PASSO 5 DE 5", "Tudo pronto",
             "A VM passou nos testes de versão, modelos, catálogo e processamento de recortes.",
             "Você pode abrir o Agente TFT e escolher o monitor ou a janela do vídeo."),
        )
        kicker, heading, description, details = pages[step]
        self.kicker.configure(text=kicker)
        self.heading.configure(text=heading)
        self.description.configure(text=description)
        self._text(details)
        labels = ("Continuar", "Verificar meu PC", "Instalar VM", "Aguarde…", "Abrir Agente TFT")
        self.next.configure(text=labels[step], state="disabled" if step == 3 else "normal")
        if step == 1 and self.preflight_ready:
            self.next.configure(text="Continuar")
        if step == 4:
            self.secondary.configure(text="Fechar", command=self._close)
            self.secondary.pack(side="right", padx=(0, 12))

    def _previous(self):
        if self.step > 0 and not self.busy:
            self._show(self.step - 1)

    def _next(self):
        if self.busy:
            return
        if self.step == 0:
            self._show(1)
        elif self.step == 1:
            if self.preflight_ready:
                self._show(2)
            else:
                self._start("preflight", self._preflight)
        elif self.step == 2:
            self._show(3)
            self._start("install", self._install)
        elif self.step == 4 and self.vm_ready:
            subprocess.Popen([str(self.app_exe)], cwd=str(self.app_exe.parent))
            self._close()

    def _secondary(self):
        self._close()

    def _start(self, name: str, fn):
        self.busy = True
        self.next.configure(state="disabled")
        self.back.configure(state="disabled")
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
        base = self.app_exe.parent
        self.installer = CoreInstaller(base / "core", Path(os.environ["LOCALAPPDATA"]) / "AgenteTFT-Core",
                                       self.app_exe)
        return self.installer.preflight(self._report).wsl_ready

    def _install(self):
        assert self.installer is not None
        self.installer.preflight(self._report)  # Recheck disk, hash and WSL immediately before mutation.
        if self.installer._call(["wsl.exe", "--status"], 30).returncode != 0:
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
                    self.next.configure(state="normal", text="Continuar")
                    self.back.configure(state="normal")
                    self._text("Verificação concluída. Continue para entender a conexão local.", append=True)
                elif kind == "install:ok":
                    self.busy = False
                    self.progress.stop()
                    self.progress.pack_forget()
                    if value == "restart":
                        self.heading.configure(text="Reinício necessário")
                        self.description.configure(text="O Windows precisa reiniciar para concluir o WSL 2. "
                                                       "O assistente continuará automaticamente no próximo login.")
                        self._text("Salve seu trabalho e reinicie o Windows quando estiver pronto.", append=True)
                        self.secondary.configure(text="Fechar", command=self._close)
                        self.secondary.pack(side="right", padx=(0, 12))
                    else:
                        self.vm_ready = True
                        self._show(4)
                elif kind.endswith(":error"):
                    self.busy = False
                    self.progress.stop()
                    self.progress.pack_forget()
                    self._log("ERRO: " + value)
                    self.heading.configure(text="Precisamos corrigir uma etapa")
                    self.description.configure(text=value)
                    self._text("Nenhuma outra distribuição WSL foi removida. Você pode tentar novamente.\n"
                               f"Log de instalação: {self.log_path}", append=True)
                    self.next.configure(text="Tentar novamente", state="normal")
                    if self.step == 3:
                        self.next.configure(command=lambda: self._start("install", self._install))
                    self.back.configure(state="normal" if self.step < 3 else "disabled")
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
    return SetupWindow(app_exe, resume="--resume-core" in sys.argv).run()
