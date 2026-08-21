import http.server
import urllib.request
import json
import urllib.parse
import datetime
import os
import sys
import subprocess
import time
import socket
import threading
from http import HTTPStatus

LIBRE_URL = "http://127.0.0.1:5000/translate"
MIDDLEWARE_PORT = 5001

# Map XUnity/LibreTranslate language codes to Argos/LibreTranslate model codes
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

# Maps (source, target_argos) to comma-separated language list for --load-only
LANG_PAIR_MODELS = {
    ('en', 'pt-BR'): 'en,pt',
    ('en', 'pt'): 'en,pt',
    ('en', 'ja'): 'en,ja',
    ('ja', 'en'): 'en,ja',
    ('pt', 'en'): 'en,pt',
    ('pt-BR', 'en'): 'en,pt',
    ('es', 'en'): 'en,es',
    ('en', 'es'): 'en,es',
    ('fr', 'en'): 'en,fr',
    ('en', 'fr'): 'en,fr',
    ('de', 'en'): 'en,de',
    ('en', 'de'): 'en,de',
    ('ko', 'en'): 'en,ko',
    ('en', 'ko'): 'en,ko',
    ('zh', 'en'): 'en,zh',
    ('en', 'zh'): 'en,zh',
    ('ru', 'en'): 'en,ru',
    ('en', 'ru'): 'en,ru',
}

# Config is read from the current working directory (game directory)
CONFIG_FILE = os.path.join(os.getcwd(), "unity_uat_config.json")
LOG_FILE = os.path.join(os.getcwd(), "BepInEx", "Translation", "pt", "Text", "_MiddlewareLog.txt")

LIBRE_PROC = None


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def _libre_up(timeout=2):
    try:
        req = urllib.request.Request(LIBRE_URL, method='GET')
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp.close()
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _log_msg(msg):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        timestamp = datetime.datetime.now().isoformat()
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write("[{}] [MW] {}\n".format(timestamp, msg))
    except Exception:
        pass


def _load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"source_language": "en", "target_language": "pt-BR"}


def log_request(text, from_lang, to_lang, result):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        timestamp = datetime.datetime.now().isoformat()
        entry = "[{}] from={} to={} text={}... result={}".format(
            timestamp, from_lang, to_lang, text[:50], result[:50])
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except Exception:
        pass


def _warmup_async(src, tgt_mapped):
    """Warmup in background thread - downloads models on first use."""
    time.sleep(3)
    try:
        print("[MW] Fazendo warmup (modelos baixados na primeira vez)...", flush=True)
        payload = json.dumps({
            'q': "Hello world, how are you?",
            'source': src if src != 'auto' else '',
            'target': tgt_mapped,
            'format': 'text'
        }).encode('utf-8')
        req = urllib.request.Request(LIBRE_URL, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        print("[MW] Warmup OK: '{}'".format(data.get('translatedText', '(sem resultado)')))
    except Exception as e:
        print("[MW] Warmup falhou: {}".format(e), flush=True)
        print("[MW] Modelos serao baixados no primeiro uso durante o jogo.", flush=True)


def _start_libretranslate_async(langs):
    """Start LibreTranslate in background if not running."""
    global LIBRE_PROC
    if _libre_up():
        print("[MW] LibreTranslate ja esta em execucao", flush=True)
        return True
    try:
        flags = 0
        if os.name == 'nt':
            flags |= int(getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        cmd = ["libretranslate", "--port", "5000", "--host", "127.0.0.1",
               "--load-only", langs, "--disable-web-ui"]
        LIBRE_PROC = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=flags)
        for _ in range(30):
            time.sleep(1)
            if _libre_up(1):
                print("[MW] LibreTranslate iniciado (PID {})".format(LIBRE_PROC.pid), flush=True)
                return True
        print("[MW] WARN: LibreTranslate nao respondeu em 30s", flush=True)
        return False
    except FileNotFoundError:
        print("[MW] ERROR: 'libretranslate' nao encontrado. Instale: pip install libretranslate", flush=True)
        return False
    except Exception as e:
        print("[MW] ERROR ao iniciar LibreTranslate: {}".format(e), flush=True)
        return False


def _get_langs():
    """Determine which languages to load based on config."""
    cfg = _load_config()
    src = cfg.get('source_language', 'en')
    tgt = LANG_MAP.get(cfg.get('target_language', 'pt-BR'), cfg.get('target_language', 'pt-BR'))
    return "{},{}".format(src, tgt)


class LibreTranslateMiddleware(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        text = params.get('text', [None])[0]
        from_lang = params.get('from', ['auto'])[0]
        to_lang = params.get('to', [None])[0]

        if text is None or to_lang is None:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.end_headers()
            self.wfile.write(b"Missing text or target language")
            return

        cfg = _load_config()
        src = cfg.get('source_language', 'en')
        tgt = cfg.get('target_language', 'pt-BR')

        if from_lang == 'auto' or from_lang == '':
            mapped_from = src if src != 'auto' else ''
        else:
            mapped_from = from_lang

        mapped_to = LANG_MAP.get(to_lang, to_lang)
        if mapped_to == 'pt' and tgt in ('pt-BR', 'pb'):
            mapped_to = 'pt-BR'

        libre_payload = json.dumps({
            'q': text,
            'source': mapped_from if mapped_from != 'auto' else '',
            'target': mapped_to,
            'format': 'text'
        }).encode('utf-8')

        try:
            req = urllib.request.Request(LIBRE_URL, data=libre_payload, method='POST')
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                translated = result.get('translatedText', '')
                log_request(text, from_lang, to_lang, translated)

                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(translated.encode('utf-8'))
        except Exception as e:
            log_request(text, from_lang, to_lang, "ERROR: {}".format(str(e)[:80]))
            if not _libre_up(1):
                _log_msg("LibreTranslate caiu, tentando reiniciar...")
                threading.Thread(target=_start_libretranslate_async,
                                 args=(_get_langs(),), daemon=True).start()
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))


def start_server():
    """Start the HTTP server immediately, then start LT+warmup in background."""
    langs = _get_langs()

    server = http.server.HTTPServer(('127.0.0.1', MIDDLEWARE_PORT), LibreTranslateMiddleware)
    print("[MW] Middleware listening on port {}".format(MIDDLEWARE_PORT), flush=True)
    _log_msg("Middleware started. Langs: {}".format(langs))

    threading.Thread(target=_start_libretranslate_async, args=(langs,), daemon=True).start()
    threading.Thread(target=_warmup_async,
                     args=(_load_config().get('source_language', 'en'),
                           LANG_MAP.get(_load_config().get('target_language', 'pt-BR'), 'pt-BR')),
                     daemon=True).start()

    server.serve_forever()


if __name__ == '__main__':
    start_server()
