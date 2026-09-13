#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
launch_unity.py - Launcher interativo do UAT para jogos Unity.

Uso:
    python launch_unity.py "D:/caminho/para/o/jogo" [src=en] [tgt=pt-BR]

Fluxo:
    1. Detecta o .exe do jogo e a pasta BepInEx
    2. Pergunta idioma original do jogo e idioma destino (menu interativo ou args)
    3. Inicia LibreTranslate + middleware (auto-start, auto-restart)
    4. Atualiza AutoTranslatorConfig.ini com o par de idiomas e endpoint
    5. Abre o jogo
    6. Monitora servidores em background; se cair, reinicia

Arquivos compartilhados (este diretorio uat-unity/):
    - launch_unity.py        (este arquivo)
    - libretranslate_middleware.py
    - lib/XUnity.Common.dll  (referencia para instalador)

Arquivos por jogo (no diretorio do jogo):
    - unity_uat_config.json  (config de idiomas do jogo)
    - BepInEx/config/AutoTranslatorConfig.ini  (config do XUnity)
    - BepInEx/Translation/<lang>/Text/  (traducoes em cache)
    - start_translation.bat  (chama este launcher)
"""
import os
import sys
import json
import time
import socket
import subprocess
import threading
import urllib.request
import urllib.error

UAT_UUNITY_DIR = os.path.dirname(os.path.abspath(__file__))
MIDDLEWARE_SCRIPT = os.path.join(UAT_UUNITY_DIR, "libretranslate_middleware.py")

# Map target language codes (XUnity -> Argos/LibreTranslate)
LANG_MAP = {
    'pt': 'pt-BR',
    'pt-BR': 'pt-BR',
    'pt_BR': 'pt-BR',
    'pb': 'pt-BR',
    'pt-pt': 'pt',
    'pt_PT': 'pt',
    'es': 'es',
    'fr': 'fr',
    'de': 'de',
    'ja': 'ja',
    'zh': 'zh',
    'ko': 'ko',
    'ru': 'ru',
    'it': 'it',
    'en': 'en',
}

LANGUAGES = [
    ("en", "English"),
    ("pt", "Portugues (Brasil)"),
    ("pt-pt", "Portugues (Portugal)"),
    ("ja", "Japanese"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
    ("ru", "Russian"),
]


def _prompt(prompt, default=""):
    """Wrapper that handles EOFError (non-interactive mode)."""
    try:
        return input(prompt).strip()
    except EOFError:
        return default


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def _libre_up(timeout=2):
    try:
        req = urllib.request.Request("http://127.0.0.1:5000/translate", method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp.close()
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _middleware_up(timeout=2):
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:5001/translate?text=test&from=en&to=pt-BR", method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp.close()
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _load_config(game_dir):
    """Load per-game config from the game directory."""
    config_path = os.path.join(game_dir, "unity_uat_config.json")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"source_language": "en", "target_language": "pt-BR"}


def _save_config(game_dir, cfg):
    config_path = os.path.join(game_dir, "unity_uat_config.json")
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("  [ERRO] Nao foi possivel salvar config: {}".format(e))


def _lang_pair_models(source, target):
    tgt_mapped = LANG_MAP.get(target, target)
    src = source if source != 'auto' else 'en'
    return "{},{}".format(src, tgt_mapped)


def _start_libretranslate(langs):
    """Start LibreTranslate if not already running."""
    if _libre_up():
        print("  [OK] LibreTranslate ja esta em execucao (porta 5000)")
        return True
    try:
        flags = 0
        if os.name == 'nt':
            flags |= int(getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        cmd = ["libretranslate", "--port", "5000", "--host", "127.0.0.1",
               "--load-only", langs, "--disable-web-ui"]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=flags)
        for _ in range(60):
            time.sleep(1)
            if _libre_up(1):
                print("  [OK] LibreTranslate iniciado (PID {})".format(proc.pid))
                return True
        print("  [ERRO] LibreTranslate nao respondeu em 60s")
        return False
    except FileNotFoundError:
        print("  [ERRO] 'libretranslate' nao encontrado no PATH.")
        print("         Instale com: pip install libretranslate")
        return False
    except Exception as e:
        print("  [ERRO] Falha ao iniciar LibreTranslate: {}".format(e))
        return False


def _start_middleware(workdir):
    """Start the middleware server if not already running."""
    if _middleware_up():
        print("  [OK] Middleware ja esta em execucao (porta 5001)")
        return True
    try:
        flags = 0
        if os.name == 'nt':
            flags |= int(getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        cmd = [sys.executable, MIDDLEWARE_SCRIPT]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=workdir, creationflags=flags)
        # Middleware starts HTTP server immediately, then LT+warmup in background
        for _ in range(15):
            time.sleep(0.5)
            if _middleware_up(1):
                print("  [OK] Middleware iniciado (PID {})".format(proc.pid))
                return True
        print("  [ERRO] Middleware nao respondeu em 7.5s")
        return False
    except Exception as e:
        print("  [ERRO] Falha ao iniciar middleware: {}".format(e))
        return False


def _warmup_libretranslate(src, tgt_mapped):
    """Trigger first translation to download Argos models."""
    print("  [INFO] Fazendo warmup (modelos sao baixados na primeira vez)...")
    try:
        payload = json.dumps({
            'q': "Hello world, how are you?",
            'source': src if src != 'auto' else '',
            'target': tgt_mapped,
            'format': 'text'
        }).encode('utf-8')
        req = urllib.request.Request("http://127.0.0.1:5000/translate", data=payload,
                                     method='POST')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        print("  [OK] Warmup: '{}'".format(data.get('translatedText', '(sem resultado)')))
        return True
    except Exception as e:
        print("  [AVISO] Warmup falhou: {}".format(e))
        print("          Modelos serao baixados no primeiro uso durante o jogo.")
        return False


def _find_game_exe(game_dir):
    """Find the main game executable."""
    exes = []
    for f in os.listdir(game_dir):
        if f.endswith('.exe') and f.lower() not in (
                'unitycrashhandler64.exe', 'unityplayer.dll',
                'bpxprocess.exe', 'steam.exe', 'steamservice.exe',
                'libretranslate.exe', 'lt.exe', 'python.exe', 'pythonw.exe'):
            exes.append(f)
    if exes:
        exes.sort(key=lambda x: len(x))
        return os.path.join(game_dir, exes[0])
    return None


def _ensure_autotranslator_config(game_dir, src, tgt):
    """Update AutoTranslatorConfig.ini with the right languages and endpoint."""
    config_dir = os.path.join(game_dir, "BepInEx", "config")
    config_path = os.path.join(config_dir, "AutoTranslatorConfig.ini")
    if not os.path.exists(config_path):
        print("  [ERRO] AutoTranslatorConfig.ini nao encontrado em: {}".format(config_path))
        print("         Rode: python install_uat_unity.py \"<caminho-do-jogo>\"")
        return False
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')
    new_lines = []
    in_service = False
    in_general = False
    in_custom = False
    from_lang = src if src != 'auto' else 'en'
    for line in lines:
        if line.strip() == '[Service]':
            in_service = True
            in_general = False
            in_custom = False
        elif line.strip() == '[General]':
            in_general = True
            in_service = False
            in_custom = False
        elif line.strip() == '[Custom]':
            in_custom = True
            in_general = False
            in_service = False
        elif line.strip().startswith('Endpoint=') and in_service:
            line = 'Endpoint=CustomTranslate'
        elif line.strip().startswith('FallbackEndpoint=') and in_service:
            line = 'FallbackEndpoint=GoogleTranslateV2'
        elif line.strip().startswith('Language=') and in_general:
            line = 'Language={}'.format(tgt)
        elif line.strip().startswith('FromLanguage=') and in_general:
            line = 'FromLanguage={}'.format(from_lang)
        elif line.strip().startswith('Url=') and in_custom:
            line = 'Url=http://127.0.0.1:5001'
        new_lines.append(line)
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    print("  [OK] AutoTranslatorConfig.ini atualizado: {} -> {}".format(src, tgt))
    return True


def _choose_cli(title, options, formatter):
    """Interactive CLI menu for language selection."""
    print("\n  {}".format(title))
    for i, opt in enumerate(options, 1):
        print("    [{:>2}] {}".format(i, formatter(opt)))
    print("    [ 0] Cancelar")
    while True:
        raw = _prompt("  Escolha: ", "0")
        try:
            val = int(raw)
            if val == 0:
                return None
            if 1 <= val <= len(options):
                return options[val - 1]
        except ValueError:
            pass
        print("  Opcao invalida. Tente novamente.")


def _interactive_language_select(game_dir):
    """Ask user for source and target languages (interactive)."""
    cfg = _load_config(game_dir)
    source = cfg.get('source_language', 'en')
    target = cfg.get('target_language', 'pt-BR')

    print("\n" + "=" * 56)
    print("  UAT Unity - Configuracao de idiomas")
    print("=" * 56)
    print("  Atual: {} -> {}".format(source, target))
    print()

    change = _prompt("  Alterar idiomas? [ENTER=manter / c=customizar]: ", "")
    if change == 'c':
        src_code = _choose_cli("Idioma original do jogo:",
                               LANGUAGES,
                               lambda x: "{} ({})".format(x[1], x[0]))
        if src_code is None:
            return None, None
        source = src_code[0]

        tgt_code = _choose_cli("Traduzir para:",
                               LANGUAGES,
                               lambda x: "{} ({})".format(x[1], x[0]))
        if tgt_code is None:
            return None, None
        target = tgt_code[0]
    else:
        custom = _prompt("  Source [ENTER={}]: ".format(source), "")
        if custom:
            source = custom
        custom = _prompt("  Target [ENTER={}]: ".format(target), "")
        if custom:
            target = custom

    tgt_mapped = LANG_MAP.get(target, target)
    if source == 'auto' or source == '':
        source = 'en'

    print("\n  Idioma do jogo: {}".format(source))
    print("  Traduzir para: {} (Argos/LT: {})".format(target, tgt_mapped))
    return source, target


def _watchdog(src, tgt_mapped, workdir):
    """Monitor servers; restart if they crash."""
    langs = "{},{}".format(src, tgt_mapped)
    while True:
        time.sleep(10)
        if not _libre_up(1):
            print("[WD] LibreTranslate caiu, reiniciando...", flush=True)
            _start_libretranslate(langs)
        if not _middleware_up(1):
            print("[WD] Middleware caiu, reiniciando...", flush=True)
            _start_middleware(workdir)


def run(game_dir=None, src=None, tgt=None):
    """Main entry point."""
    if not game_dir:
        game_dir = os.getcwd()
    game_dir = os.path.abspath(game_dir)

    print("\n" + "=" * 56)
    print("  UAT Unity - Universal Auto Translator for Unity")
    print("=" * 56)
    print("\n  Jogo: {}".format(os.path.basename(game_dir)))
    print("  Pasta: {}".format(game_dir))

    bepinex_dir = os.path.join(game_dir, "BepInEx")
    if not os.path.exists(bepinex_dir):
        print("\n  [ERRO] BepInEx nao encontrado em: {}".format(bepinex_dir))
        print("         Rode: python install_uat_unity.py \"<caminho-do-jogo>\"")
        _prompt("\n  Pressione ENTER para sair...")
        return 1

    game_exe = _find_game_exe(game_dir)
    if not game_exe:
        print("\n  [ERRO] Nenhum .exe de jogo encontrado em: {}".format(game_dir))
        _prompt("\n  Pressione ENTER para sair...")
        return 1
    print("\n  Executavel: {}".format(os.path.basename(game_exe)))

    # Language selection
    if src and tgt:
        source = src
        target = tgt
        print("\n  Configuracao via linha de comando: {} -> {}".format(source, target))
    else:
        result = _interactive_language_select(game_dir)
        if result == (None, None):
            print("\n  Cancelado pelo usuario.")
            return 0
        source, target = result

    tgt_mapped = LANG_MAP.get(target, target)
    langs = "{},{}".format(source, tgt_mapped)

    # Save per-game config
    _save_config(game_dir, {"source_language": source, "target_language": target})
    print("\n  Configuracao salva em: {}".format(os.path.join(game_dir, "unity_uat_config.json")))

    # Update AutoTranslatorConfig.ini
    print("\n  -> Configurando XUnity AutoTranslator...")
    if not _ensure_autotranslator_config(game_dir, source, target):
        _prompt("\n  Pressione ENTER para sair...")
        return 1

    # Start servers
    print("\n  -> Iniciando servidores de traducao...")
    print("     LibreTranslate modelos: {}".format(langs))
    if not _start_libretranslate(langs):
        print("\n  [ERRO] Nao foi possivel iniciar LibreTranslate.")
        print("         O jogo abrira sem traducao.")
        _prompt("\n  Pressione ENTER para abrir o jogo mesmo assim...")
        try:
            os.startfile(game_exe)
        except Exception:
            pass
        return 0

    if not _start_middleware(game_dir):
        print("\n  [AVISO] Middleware falhou. Tente reiniciar.")
        _prompt("\n  Pressione ENTER para sair...")
        return 1

    # Warmup
    _warmup_libretranslate(source, tgt_mapped)

    # Start watchdog in background
    wd = threading.Thread(target=_watchdog, args=(source, tgt_mapped, game_dir),
                          daemon=True)
    wd.start()

    # Launch game
    print("\n  -> Abrindo jogo: {}".format(os.path.basename(game_exe)))
    print("     (feche o jogo para encerrar o servidor)")
    print()
    try:
        proc = subprocess.Popen([game_exe], cwd=game_dir)
        proc.wait()
    except Exception as e:
        print("  [ERRO] Falha ao abrir o jogo: {}".format(e))
        _prompt("\n  Pressione ENTER para sair...")
        return 1

    print("\n  [OK] Jogo encerrado. Servidor continua em execucao.")
    return 0


def main():
    args = sys.argv[1:]
    game_dir = None
    src = None
    tgt = None
    for arg in args:
        if arg.startswith("src="):
            src = arg[4:]
        elif arg.startswith("tgt="):
            tgt = arg[4:]
        elif os.path.isdir(arg):
            game_dir = arg
    sys.exit(run(game_dir, src, tgt))


if __name__ == "__main__":
    main()
