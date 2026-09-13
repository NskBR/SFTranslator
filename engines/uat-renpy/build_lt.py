#!/usr/bin/env python
"""
build_lt.py - Empacota o LibreTranslate como exe portatil (PyInstaller).

Uso:
    python build_lt.py

O que faz:
  1. Copia os modelos Argos ja baixados no PC atual para UAT-Pack/models/
     (en->pt, en->pb, pt->en, minisbd) - "deixa o tradutor dentro do pack".
  2. Compila _run_lt.py + libretranslate + dependencias em:
        UAT-Pack/lt.exe   (modo onedir: lt.exe + _internal/ na raiz do pack)
  3. Modelos ficam em UAT-Pack/models/, o exe/os usa via XDG_DATA_HOME.

Depois, basta colar o CONTEUDO da pasta UAT-Pack na raiz do jogo (o lt.exe
fica ao lado do exe do game): o uat_hook.py detecta lt.exe e usa ELE
automaticamente (nao precisa de Python nem de instalacao no PC final).

Requisitos: Python 3.9+ com libretranslate instalado. Internet apenas na
primeira execucao do exe (download dos modelos que ainda faltarem).
"""
import os
import sys
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
UAT_DIR = os.path.join(HERE, "uat")
MODELS_DIR = os.path.join(HERE, "models")   # UAT-Pack/models (modelos na raiz do pack)
ARGOS_HOME = os.path.join(os.path.expanduser("~"), ".local", "share", "argos-translate")
MINISBD_CACHE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Cache", "minisbd")

COLLECT_ALL = [
    "libretranslate",
    "argostranslate",
    "argostranslatefiles",
    "minisbd",
    "flask",
    "flask_cors",
    "flask_babel",
    "flask_swagger",
    "flask_swagger_ui",
    "flask_limiter",
    "waitress",
    "apscheduler",
    "langdetect",
    "lexilang",
    "expiringdict",
    "polib",
    "prometheus_client",
    "sentencepiece",
    "ctranslate2",
]

HIDDEN_IMPORTS = [
    "waitress",
    "flask_cors",
    "werkzeug",
    "argostranslate.settings",
    "argostranslate.package",
    "libretranslate.main",
    "libretranslate.app",
]


def _run(cmd, **kw):
    print(">> " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit(r.returncode)


def copy_models():
    if not os.path.isdir(ARGOS_HOME):
        print("[ERRO] Modelos Argos nao encontrados em: " + ARGOS_HOME)
        print("       Rode antes: python uat/_run_lt.py   (baixa os modelos)")
        print("       Ou compile sem modelos: modelos sao baixados no 1o uso do exe.")
        os.makedirs(os.path.join(MODELS_DIR, "argos-translate"), exist_ok=True)
        return
    shutil.rmtree(MODELS_DIR, ignore_errors=True)
    dst = os.path.join(MODELS_DIR, "argos-translate")
    for item in ("packages", "minisbd", "index.json"):
        src = os.path.join(ARGOS_HOME, item)
        d = os.path.join(dst, item)
        if os.path.isdir(src):
            shutil.copytree(src, d)
        elif os.path.isfile(src):
            os.makedirs(dst, exist_ok=True)
            shutil.copy2(src, d)
    # minisbd (modelos de separacao de frases) tambem, se existir em outro lugar
    if os.path.isdir(MINISBD_CACHE):
        d = os.path.join(MODELS_DIR, "minisbd")
        shutil.copytree(MINISBD_CACHE, d, dirs_exist_ok=True)
    print("[OK] Modelos copiados para: " + dst)


def build_exe():
    py = sys.executable
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller nao encontrado. Instalando...")
        _run([py, "-m", "pip", "install", "pyinstaller"])
    # Limpa artefatos de builds antigos (NUNCA mexe em uat/, game/ ou .py)
    shutil.rmtree(os.path.join(HERE, "build"), ignore_errors=True)
    shutil.rmtree(os.path.join(HERE, "_internal"), ignore_errors=True)
    if os.path.isfile(os.path.join(HERE, "lt.exe")):
        os.remove(os.path.join(HERE, "lt.exe"))
    shutil.rmtree(os.path.join(HERE, "lt"), ignore_errors=True)   # layout antigo (lt/lt.exe)

    cmd = [py, "-m", "PyInstaller", "--noconfirm", "--onedir", "--name", "lt",
           "--distpath", HERE,
           "--workpath", os.path.join(HERE, "build"),
           "--specpath", HERE]
    for m in COLLECT_ALL:
        cmd += ["--collect-all", m]
    for m in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", m]
    cmd.append(os.path.join(UAT_DIR, "_run_lt.py"))
    _run(cmd)

    # onedir gera HERE/lt/* -> sobe um nivel: lt.exe fica na RAIZ do UAT-Pack
    staged = os.path.join(HERE, "lt")
    if os.path.isdir(staged):
        for item in os.listdir(staged):
            shutil.move(os.path.join(staged, item), os.path.join(HERE, item))
        shutil.rmtree(staged)

    exe = os.path.join(HERE, "lt.exe")
    if not os.path.exists(exe):
        print("[ERRO] Build nao gerou o exe: " + exe)
        sys.exit(1)
    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(os.path.join(HERE, "_internal")) for f in fs) // (1024 * 1024)
    print("[OK] Exe gerado: " + exe)
    print("[OK] Tamanho total (lt.exe + _internal): ~%d MB" % size)
    print("[OK] Modelos: " + MODELS_DIR)


def smoke_test():
    import os as _os
    exe = os.path.join(HERE, "lt.exe")
    env = dict(os.environ, LT_PORT="5099", PYTHONIOENCODING="utf-8", LT_API_KEYS="")
    smoke_dir = os.path.join(UAT_DIR, "UAlogs")
    try:
        _os.makedirs(smoke_dir)
    except Exception:
        pass
    print("[TESTE] Subindo exe (modo __server__) na porta 5099...")
    with open(os.path.join(smoke_dir, "smoke.log"), "w", encoding="utf-8", errors="replace") as f:
        p = subprocess.Popen([exe, "__server__"], env=env, stdout=f, stderr=f)
    import time, json, urllib.request
    url = "http://127.0.0.1:5099/translate"
    ok = False
    for _ in range(120):
        time.sleep(1)
        try:
            req = urllib.request.Request(url, method="GET")
            try:
                urllib.request.urlopen(req, timeout=2)
            except:
                pass
            body = json.dumps({"q": "Hello my friend", "source": "en", "target": "pt",
                               "format": "text"}).encode("utf-8")
            rq = urllib.request.Request(url, data=body,
                                        headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(rq, timeout=30) as r:
                print("[TESTE] Traducao: " + r.read().decode("utf-8")[:120])
                ok = True
                break
        except Exception:
            continue
    p.terminate()
    try:
        p.wait(timeout=15)
    except Exception:
        p.kill()
    if not ok:
        print("[TESTE] FALHOU. Veja uat/UAlogs/smoke.log")
        return 1
    print("[TESTE] OK")
    return 0


def main():
    if "no-models" not in sys.argv:
        copy_models()
    build_exe()
    if "smoke" in sys.argv:
        sys.exit(smoke_test())
    print("\nPronto! O UAT vai usar o exe automaticamente. Distribua o pack inteiro (uat/).")


if __name__ == "__main__":
    main()