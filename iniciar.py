#!/usr/bin/env python3
"""NEXUS — inicializador local (Windows, macOS e Linux).

Uso:  python iniciar.py            (ou dois cliques em iniciar.bat no Windows)
      python iniciar.py --rebuild  (recompila a interface)
      python iniciar.py --porta 8080

Faz tudo sozinho: cria o ambiente Python, instala as dependências, compila a interface
(na primeira vez) e abre o NEXUS no navegador em um único endereço.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consoles Windows antigos
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "services" / "engine"
WEB = ROOT / "apps" / "web"
VENV = ENGINE / ".venv"
IS_WIN = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def info(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def fail(msg: str, hint: str = "") -> None:
    print(f"\n[ERRO] {msg}", flush=True)
    if hint:
        print(f"       {hint}", flush=True)
    print("\nSe não conseguir resolver, copie TODO o texto acima e envie para o suporte.", flush=True)
    sys.exit(1)


def run(cmd: list[str], cwd: Path, what: str) -> None:
    print("    $ " + " ".join(str(c) for c in cmd), flush=True)
    try:
        code = subprocess.call(cmd, cwd=str(cwd), shell=False)
    except FileNotFoundError:
        fail(f"Comando não encontrado ao {what}: {cmd[0]}")
    if code != 0:
        fail(f"Falha ao {what} (código {code}).", "Veja a mensagem logo acima desta linha.")


def check_python() -> None:
    if sys.version_info < (3, 10):
        fail(f"Python {sys.version.split()[0]} é antigo demais. O NEXUS precisa do Python 3.10 ou mais novo.",
             "Baixe em https://www.python.org/downloads/ (no Windows, marque 'Add python.exe to PATH').")
    print(f"    Python {sys.version.split()[0]} OK")


def setup_backend() -> None:
    req = ENGINE / "requirements.txt"
    stamp = VENV / ".nexus-requirements"
    digest = hashlib.sha256(req.read_bytes()).hexdigest()
    if not VENV_PY.exists():
        info("Criando ambiente Python (só na primeira vez)")
        run([sys.executable, "-m", "venv", str(VENV)], ROOT, "criar o ambiente Python")
    if not stamp.exists() or stamp.read_text().strip() != digest:
        info("Instalando dependências do servidor (pode levar 1–2 minutos)")
        run([str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"],
            ENGINE, "atualizar o pip")
        run([str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)],
            ENGINE, "instalar as dependências do servidor")
        stamp.write_text(digest)
    else:
        print("    Dependências do servidor OK")


def setup_frontend(rebuild: bool) -> None:
    dist = WEB / "dist" / "index.html"
    if dist.exists() and not rebuild:
        print("    Interface já compilada OK")
        return
    npm = shutil.which("npm")
    if not npm:
        fail("Node.js não encontrado (necessário só para compilar a interface na primeira vez).",
             "Instale a versão LTS em https://nodejs.org/ , feche e reabra o terminal, e rode de novo.")
    info("Instalando dependências da interface (só na primeira vez, 1–3 minutos)")
    run([npm, "ci" if (WEB / "package-lock.json").exists() else "install", "--no-audit", "--no-fund"],
        WEB, "instalar as dependências da interface")
    info("Compilando a interface")
    run([npm, "run", "build"], WEB, "compilar a interface")


def free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    fail(f"Nenhuma porta livre entre {preferred} e {preferred + 19}.")
    return preferred


def open_when_ready(url: str) -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1)
            print(f"\n    NEXUS no ar: {url}\n    (Para encerrar, pressione Ctrl+C nesta janela.)\n", flush=True)
            webbrowser.open(url)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    print("\n    O servidor está demorando para responder; veja as mensagens acima.", flush=True)


def main() -> None:
    args = sys.argv[1:]
    port = 8000
    if "--porta" in args:
        try:
            port = int(args[args.index("--porta") + 1])
        except (IndexError, ValueError):
            fail("Uso: python iniciar.py --porta 8080")
    print("NEXUS · Enterprise Tax Intelligence — inicialização local")
    info("Verificando requisitos")
    check_python()
    setup_backend()
    setup_frontend("--rebuild" in args)
    port = free_port(port)
    url = f"http://localhost:{port}"
    info(f"Iniciando o NEXUS em {url}")
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    env = dict(os.environ, AUTH_MODE="dev", PYTHONUTF8="1")
    try:
        code = subprocess.call([str(VENV_PY), "-m", "uvicorn", "nexus_engine.api.app:app",
                                "--host", "127.0.0.1", "--port", str(port)], cwd=str(ENGINE), env=env)
    except KeyboardInterrupt:
        code = 0
    if code not in (0, 130, 3221225786):  # 3221225786 = Ctrl+C no Windows
        fail(f"O servidor parou com código {code}.", "Veja a mensagem logo acima desta linha.")
    print("\nNEXUS encerrado.")


if __name__ == "__main__":
    main()
