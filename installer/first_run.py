"""LeIA first-run setup: cria venv, instala dependências, pré-baixa modelos.

Roda dentro de uma janela tkinter com barra de progresso e log em tempo real.
É invocado pelo launcher.bat quando %APPDATA%\\LeIA\\.setup_complete não existe.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

APP_NAME = "LeIA"
APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / APP_NAME
VENV_DIR = APPDATA / "venv"
MODELS_DIR = APPDATA / "models"
LOGS_DIR = APPDATA / "logs"
SETUP_FLAG = APPDATA / ".setup_complete"

INSTALL_DIR = Path(__file__).resolve().parent
REQUIREMENTS = INSTALL_DIR / "requirements.txt"
EMBED_PY = INSTALL_DIR / "python" / "python.exe"


class SetupRunner:
    def __init__(self, log_queue: queue.Queue, on_done):
        self.log_queue = log_queue
        self.on_done = on_done

    def log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def run_cmd(self, cmd: list[str]) -> None:
        self.log(f"> {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(INSTALL_DIR),
        )
        for line in proc.stdout:
            self.log(line.rstrip())
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"Comando falhou (rc={proc.returncode}): {' '.join(cmd)}")

    def has_nvidia_gpu(self) -> bool:
        try:
            r = subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, timeout=10
            )
            return r.returncode == 0
        except Exception:
            return False

    def step_appdata(self) -> None:
        self.log("[1/5] Preparando diretórios em %APPDATA%\\LeIA…")
        for d in (APPDATA, MODELS_DIR, LOGS_DIR):
            d.mkdir(parents=True, exist_ok=True)

    def step_venv(self) -> None:
        self.log("[2/5] Criando ambiente Python isolado…")
        if VENV_DIR.exists():
            self.log("  venv já existe, reutilizando.")
            return
        self.run_cmd([str(EMBED_PY), "-m", "venv", str(VENV_DIR)])

    def step_pip(self) -> None:
        self.log("[3/5] Atualizando pip…")
        py = VENV_DIR / "Scripts" / "python.exe"
        # setuptools<81: 81+ removeu o pkg_resources, do qual o chatterbox depende.
        self.run_cmd([str(py), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools<81"])

    def step_requirements(self) -> None:
        self.log("[4/5] Instalando dependências (PyTorch, Chatterbox, etc.)…")
        py = VENV_DIR / "Scripts" / "python.exe"
        req = REQUIREMENTS if REQUIREMENTS.exists() else INSTALL_DIR.parent / "requirements.txt"
        if self.has_nvidia_gpu():
            self.log("  GPU NVIDIA detectada — instalando PyTorch + CUDA 12.1.")
            self.run_cmd([str(py), "-m", "pip", "install", "-r", str(req)])
        else:
            self.log("  Sem GPU NVIDIA — instalando PyTorch CPU.")
            cpu_req = self._cpu_requirements_text(req)
            tmp = APPDATA / "requirements-cpu.txt"
            tmp.write_text(cpu_req, encoding="utf-8")
            self.run_cmd([str(py), "-m", "pip", "install", "-r", str(tmp)])

    @staticmethod
    def _cpu_requirements_text(req: Path) -> str:
        out = []
        for line in req.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("--extra-index-url"):
                continue
            if stripped.startswith("torch==") or stripped.startswith("torchaudio=="):
                pkg = stripped.split("==")[0]
                version = stripped.split("==")[1].split("+")[0]
                out.append(f"{pkg}=={version}")
                continue
            out.append(line)
        return "\n".join(out)

    def step_models(self) -> None:
        self.log("[5/5] Baixando modelo de voz (Chatterbox)… isso pode demorar.")
        py = VENV_DIR / "Scripts" / "python.exe"
        snippet = (
            "import torch;"
            "from chatterbox.mtl_tts import ChatterboxMultilingualTTS;"
            "ChatterboxMultilingualTTS.from_pretrained("
            "device='cuda' if torch.cuda.is_available() else 'cpu');"
            "import nltk; nltk.download('punkt_tab', quiet=True);"
            "print('models ok')"
        )
        self.run_cmd([str(py), "-c", snippet])

    def run(self) -> None:
        try:
            self.step_appdata()
            self.step_venv()
            self.step_pip()
            self.step_requirements()
            self.step_models()
            SETUP_FLAG.write_text("ok", encoding="utf-8")
            self.log("\nConfiguração concluída ✓")
            self.on_done(True, None)
        except Exception as exc:
            self.log(f"\nERRO: {exc}")
            self.on_done(False, str(exc))


class SetupWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Configurando {APP_NAME}")
        self.geometry("720x460")
        self.configure(bg="#1a1a1a")

        title = tk.Label(
            self,
            text=f"Configurando o {APP_NAME} pela primeira vez",
            font=("Segoe UI", 14, "bold"),
            fg="#e8e8e8",
            bg="#1a1a1a",
        )
        title.pack(pady=(16, 6))
        sub = tk.Label(
            self,
            text="Isso leva entre 5 e 15 minutos. Mantenha a janela aberta.",
            fg="#9aa0a6",
            bg="#1a1a1a",
        )
        sub.pack(pady=(0, 10))

        self.progress = ttk.Progressbar(self, mode="indeterminate", length=600)
        self.progress.pack(pady=(0, 12))
        self.progress.start(15)

        self.log_box = tk.Text(
            self,
            height=18,
            bg="#0e0e0e",
            fg="#cccccc",
            insertbackground="#cccccc",
            font=("Consolas", 9),
            wrap="none",
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=8)

        self.close_btn = tk.Button(
            self,
            text="Fechar",
            command=self.destroy,
            state="disabled",
            bg="#2a2a2a",
            fg="#e8e8e8",
            activebackground="#3a3a3a",
            activeforeground="#ffffff",
            borderwidth=0,
            padx=18,
            pady=6,
        )
        self.close_btn.pack(pady=(0, 12))

        self.log_queue: queue.Queue = queue.Queue()
        self.runner = SetupRunner(self.log_queue, self.on_finish)
        self.after(100, self._poll_log)
        threading.Thread(target=self.runner.run, daemon=True).start()

    def _poll_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_box.insert("end", line + "\n")
                self.log_box.see("end")
        except queue.Empty:
            pass
        self.after(120, self._poll_log)

    def on_finish(self, ok: bool, error: str | None) -> None:
        self.progress.stop()
        self.progress.config(mode="determinate", value=100 if ok else 0)
        self.close_btn.config(state="normal")
        if ok:
            self.close_btn.config(text="Concluir e abrir LeIA")


def main() -> int:
    if not EMBED_PY.exists():
        sys.stderr.write(f"Python embeddable não encontrado em {EMBED_PY}\n")
        return 1
    app = SetupWindow()
    app.mainloop()
    return 0 if SETUP_FLAG.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
