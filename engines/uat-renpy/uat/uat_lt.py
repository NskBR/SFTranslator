# -*- coding: utf-8 -*-
"""
uat_lt.py - Gerenciador do servidor LibreTranslate embutido no UAT.

Com o provider "local", o UAT nao depende mais de o usuario instalar e
rodar o LibreTranslate na mao. O gerenciador garante que um servidor local
esteja de pe, tentando, em ordem:

  1. ping no endpoint configurado        (servidor ja pode estar rodando)
  2. uat/lt/bin/lt.exe                   (build PyInstaller - 100% portatil)
  3. uat/.lt-venv/Scripts/python.exe     (venv criado na instalacao --setup-lt)
  4. python do sistema / embutido com libretranslate ja instalado
  5. cria venv local + pip install libretranslate (primeira vez, internet)

Depois sobe o servidor como subprocesso (sem janela), faz polling ate
responder, roda um warmup (dispara download dos modelos na primeira vez)
e fica de vigia: se cair reinicia, e detecta se o usuario abriu o exe
manualmente ("abrir o lt.exe e depois o jogo" tambem funciona).

NUNCA bloqueia o jogo: se nao der para subir, as chamadas de traducao
retornam o texto original e o jogo segue normalmente.

Logs vao todos para a pasta UAlogs/ (uat/UAlogs/lt_server.log).

CLI de instalacao:
    python uat/uat_lt.py --setup-lt
        instala (venv + libretranslate) e faz o warmup AGORA, para o jogo
        ja abrir traduzido na primeira execucao.
"""
import os
import sys
import json
import time
import threading
import subprocess

# --- urllib compativel Python 2.7 (Ren'Py legado) / Python 3 ---
try:
    import urllib.request as _ut
    import urllib.error as _uer
    import urllib.parse as _up
    _IS_PY3 = True
except ImportError:
    import urllib2 as _ut
    import urlparse as _up
    _IS_PY3 = False

    class _uer(object):
        HTTPError = _ut.HTTPError


UAT_DIR = os.path.dirname(os.path.abspath(__file__))
LT_DIR = os.path.join(UAT_DIR, "lt")
LT_EXE = os.path.join(os.path.dirname(UAT_DIR), "lt", "lt.exe")   # <jogo>/lt/lt.exe
LT_EXE_ROOT = os.path.join(os.path.dirname(UAT_DIR), "lt.exe")    # conteudo de lt/ colado na raiz do jogo
LT_EXE_LEGACY = os.path.join(LT_DIR, "bin", "lt.exe")             # instalacoes antigas
VENV_DIR = os.path.join(UAT_DIR, ".lt-venv")
VENV_PY = os.path.join(VENV_DIR, "Scripts", "python.exe")
LOGS_DIR = os.path.join(UAT_DIR, "UAlogs")
SERVER_LOG = os.path.join(LOGS_DIR, "lt_server.log")
RUNNER = os.path.join(UAT_DIR, "_run_lt.py")
CONFIG_PATH = os.path.join(UAT_DIR, "uat_config.json")

_started = False
_ready = False
_proc = None
_give_up_at = None
_lock = threading.Lock()
_warmup_lock = threading.Lock()


def _urlopen(url, data=None, headers=None, timeout=None, method=None):
    """wrapper urllib compat (py2 nao aceita method=, py3 aceita)."""
    if _IS_PY3 and method is not None:
        req = _ut.Request(url, data=data, headers=headers or {}, method=method)
    else:
        req = _ut.Request(url, data=data, headers=headers or {})
    return _ut.urlopen(req, timeout=timeout)


def _ensure_logs_dir():
    try:
        if not os.path.isdir(LOGS_DIR):
            os.makedirs(LOGS_DIR)
    except Exception:
        pass


def _log(msg):
    try:
        import uat_log
        # Garante o logger inicializado (CLI roda sem uat_hook; no jogo ja esta).
        if not hasattr(uat_log.UATLogger, "_console"):
            uat_log.UATLogger.init(log_path=None, show_console=True)
        uat_log.UATLogger.info("[LT] " + msg)
    except Exception:
        try:
            print("[LT] " + msg, flush=True)
        except Exception:
            pass


def is_ready():
    """True quando o servidor local ja fez o warmup (pronto pra traduzir)."""
    return _ready


def deadline():
    """Ate quando o worker espera o servidor subir antes de descartar a fila."""
    return _give_up_at if _give_up_at else 0


def _cfg():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _cfg_endpoint():
    try:
        return _cfg().get("local", {}).get("endpoint", "http://127.0.0.1:5000/translate")
    except Exception:
        return "http://127.0.0.1:5000/translate"


def _server_port():
    try:
        return _up.urlparse(_cfg_endpoint()).port or 5000
    except Exception:
        return 5000


def _server_up(timeout=1.5):
    """Servidor respondendo? GET no endpoint (qualquer HTTP != erro de conexao)."""
    try:
        r = _urlopen(_cfg_endpoint(), timeout=timeout, method="GET")
        try:
            code = r.getcode()
            if code is None:
                code = 500
            return code < 500
        finally:
            try:
                r.close()
            except Exception:
                pass
    except _uer.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def _warmup_sync():
    """Traducao de teste sincrona. Dispara o download dos modelos na 1a vez."""
    try:
        cfg = _cfg()
        body = json.dumps({
            "q": ["Hello world, how are you?", "Good morning, my friend."],
            "source": cfg.get("source_language", "en"),
            "target": cfg.get("target_language", "pt-BR"),
            "format": "text",
        }).encode("utf-8")
        r = _urlopen(_cfg_endpoint(), data=body,
                     headers={"Content-Type": "application/json"},
                     timeout=1200, method="POST")
        try:
            data = r.read().decode("utf-8", "replace")
        finally:
            try:
                r.close()
            except Exception:
                pass
        _log("Warmup OK: " + data[:120].replace("\n", " "))
        return True
    except Exception as e:
        _log("Warmup falhou: %r" % (e,))
        return False


def _warmup():
    """Versao de runtime: roda em thread pra nao travar o jogo."""
    global _ready, _give_up_at
    with _warmup_lock:
        if _ready:
            return
        if not _warmup_sync():
            _log("Servidor respondeu, mas o warmup falhou; mantendo fila em espera.")
            return
        _ready = True
        _give_up_at = None
        _log("Servidor local pronto (traducoes locais ativas).")


def _python_has_lt(py):
    try:
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        r = subprocess.run([py, "-c", "import libretranslate"],
                           capture_output=True, timeout=25, creationflags=flags)
        return r.returncode == 0
    except Exception:
        return False


def _python_ok(py):
    try:
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        r = subprocess.run([py, "-c", "import venv, ensurepip"],
                           capture_output=True, timeout=25, creationflags=flags)
        return r.returncode == 0
    except Exception:
        return False


def _make_venv(base):
    try:
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _log("Criando venv em " + VENV_DIR + " (base: " + str(base) + ")...")
        r = subprocess.run([base, "-m", "venv", VENV_DIR],
                           capture_output=True, timeout=300, creationflags=flags)
        if r.returncode != 0 or not os.path.exists(VENV_PY):
            _log("Falha criar venv: " + (r.stderr or b"").decode("utf-8", "replace")[:300])
            return False
        _log("Instalando libretranslate no venv (1a vez, pode demorar)...")
        r = subprocess.run([VENV_PY, "-m", "pip", "install", "--quiet",
                            "--disable-pip-version-check", "libretranslate"],
                           capture_output=True, timeout=1800, creationflags=flags)
        if r.returncode != 0:
            _log("pip install falhou: " + (r.stderr or b"").decode("utf-8", "replace")[:300])
            return False
        _log("libretranslate instalado no venv.")
        return _python_has_lt(VENV_PY)
    except Exception as e:
        _log("Falha criar venv: %r" % (e,))
        return False


def _find_lt_exe():
    """Localiza o exe embutido: lt/lt.exe na raiz, lt.exe na raiz, ou antigo."""
    for c in (LT_EXE, LT_EXE_ROOT, LT_EXE_LEGACY):
        if os.path.isfile(c):
            return c
    return None


def _ensure_interpreter():
    """Retorna (interprete, descricao) pronto pra rodar o servidor, ou None."""
    exe = _find_lt_exe()
    if exe:
        return exe, "exe embutido (PyInstaller)"
    candidates = (
        (VENV_PY, "venv", True),
        (sys.executable, "python do jogo", True),
        ("python", "python do PATH", False),
        ("py", "py launcher", False),
    )
    for py, desc, must_exist in candidates:
        if not py:
            continue
        if must_exist and not os.path.exists(py):
            continue
        if _python_has_lt(py):
            return py, desc
    # Nenhum python com libretranslate: cria venv local com o melhor disponivel
    for base in (sys.executable, "python", "py"):
        if _python_ok(base):
            if _make_venv(base):
                return VENV_PY, "venv (criado na hora)"
            break
    _log("ERRO: nenhum Python com libretranslate disponivel.")
    _log("      Abrindo exe manual: uat/lt/bin/lt.exe. Ou use prov=google_free na config.")
    return None


def _start_server(interp):
    global _proc
    _ensure_logs_dir()
    flags = 0
    if os.name == "nt":
        flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    env = dict(os.environ)
    env["LT_PORT"] = str(_server_port())
    env["LT_API_KEYS"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        fh = open(SERVER_LOG, "a", encoding="utf-8", errors="replace")
    except Exception:
        fh = None
    except TypeError:
        fh = None
    try:
        # "__server__" = so sobe o servidor (nao tenta iniciar o jogo)
        # roda com cwd na pasta de logs -> os arquivos do LT (dbs/caches) ficam la
        _proc = subprocess.Popen([interp, RUNNER, "__server__"], cwd=LOGS_DIR, env=env,
                                 stdout=fh, stderr=fh, creationflags=flags)
        return _proc
    except Exception as e:
        _log("Falha iniciar servidor: %r" % (e,))
        return None


def _wait_server_up(timeout):
    start = time.time()
    while time.time() - start < timeout:
        if _server_up():
            return True
        p = _proc
        if p is not None and p.poll() is not None:
            _log("AVISO: processo do servidor morreu durante a espera.")
            return False
        time.sleep(0.7)
    return False


def _mark_ready(reason):
    global _ready, _give_up_at
    _ready = True
    _give_up_at = None
    _log("Servidor local pronto: " + reason)


def ensure_server():
    """Chamado pelo hook em thread separada (nunca bloqueia o jogo)."""
    global _started
    if os.environ.get("SFTRANSLATOR_MANAGED_RUNTIME") == "1":
        if _server_up():
            _warmup()
        else:
            _log("Servidor gerenciado pelo SFTranslator indisponivel. Reabra a sessao no aplicativo.")
        return
    with _lock:
        if _started:
            return
        _started = True
    _log("Provider local. Garantindo servidor: " + _cfg_endpoint())
    # Vigia roda SEMPRE: detecta exe aberto a mao, morte e reinicia.
    threading.Thread(target=_watchdog, daemon=True).start()
    _ensure_running()


def _ensure_running():
    global _give_up_at
    if _give_up_at is None or time.time() > _give_up_at:
        _give_up_at = time.time() + 300
    if _server_up():
        _give_up_at = None
        _warmup()
        return
    r = _ensure_interpreter()
    if r is None:
        _log("ERRO: sem tradutor local disponivel. O jogo usa o texto original.")
        return
    interp, desc = r
    _log("Subindo servidor LibreTranslate (" + desc + ")...")
    p = _start_server(interp)
    if p is None:
        return
    _log("Processo PID " + str(p.pid) + " (log: " + SERVER_LOG + ")")
    if _wait_server_up(120):
        _give_up_at = None
        _warmup()
    else:
        _give_up_at = time.time() + 240
        _log("ERRO: servidor nao respondeu em 120s. Log: " + SERVER_LOG)


def _watchdog():
    global _ready
    restarts = 0
    tick = 5
    while True:
        time.sleep(tick)
        if _server_up():
            if not _ready:
                _log("WATCHDOG: servidor detectado. Fazendo warmup...")
                _warmup()
            continue
        if _ready:
            _ready = False
            _log("WATCHDOG: servidor caiu.")
        if restarts >= 3:
            _log("WATCHDOG: desistindo de reiniciar. Abra uat/lt/bin/lt.exe manualmente.")
            continue
        _log("WATCHDOG: tentando subir/restart (" + str(restarts + 1) + "/3)...")
        r = _ensure_interpreter()
        if r is None:
            _log("WATCHDOG: sem interprete. Desistindo.")
            return
        interp, desc = r
        _start_server(interp)
        restarts += 1
        if _wait_server_up(90):
            _ready = True
            _give_up_at = None
            _log("WATCHDOG: servidor reiniciado e pronto (" + desc + ").")


def setup_main():
    """CLI: prepara o servidor local agora (instala + warmup)."""
    _log("Setup do servidor local (--setup-lt). Pode demorar na primeira vez.")
    r = _ensure_interpreter()
    if r is None:
        _log("ERRO: falhou preparar o servidor local.")
        return 1
    interp, desc = r
    _log("Interprete escolhido: " + desc)
    if _server_up():
        _log("Servidor ja esta de pe; warmup...")
    else:
        p = _start_server(interp)
        if p is None:
            return 1
        _log("Servidor iniciado (PID " + str(p.pid) + "). Aguardando...")
        if not _wait_server_up(600):
            _log("ERRO: servidor nao respondeu em 600s. Veja " + SERVER_LOG)
            return 1
    _log("Servidor no ar. Warmup (download de modelos na 1a vez)...")
    ok = _warmup_sync()
    p = _proc
    if p is not None:
        try:
            p.terminate()
            p.wait(timeout=15)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    _log("Setup concluido: " + (
        "modelos prontos." if ok else "servidor OK (modelos serao baixados quando o jogo abrir)."))
    return 0


def main():
    args = sys.argv[1:]
    if "--setup-lt" in args:
        sys.exit(setup_main())
    print("Uso:")
    print("  python uat_lt.py --setup-lt    -> prepara o servidor local agora (instala + warmup)")
    print("  (sem argumentos o modulo e usado pelo uat_hook.py em runtime)")


if __name__ == "__main__":
    main()
