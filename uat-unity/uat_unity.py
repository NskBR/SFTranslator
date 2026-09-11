#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# uat_unity.py - UAT-Unity (Universal Auto Translator for Unity) - MODULO UNIFICADO.
#
# Pasta UAT-UNITY colada DENTRO da pasta do jogo:
#   Jogo/UAT-UNITY/
#       uat_unity.py            <- este arquivo (servidor + assistente + menu)
#       models/                 <- modelos Argos (baixados sob demanda)
#       unity_uat_config.json   <- config por jogo (source/target, porta)
#       Logs/                   <- logs do servidor
#
# Fluxo (plug-and-play):
#   1. Primeira execucao (sem BepInEx no jogo):
#        - detecta runtime (Mono/IL2CPP)
#        - baixa BepInEx (5 Mono ou 6 IL2CPP) + XUnity AutoTranslator do GitHub
#        - extrai no jogo e gera AutoTranslatorConfig.ini (CustomTranslate -> nosso server)
#        - wizard: pergunta idioma origem/destino -> baixa modelo Argos
#   2. Execucoes seguintes:
#        - menu: [ENTER] iniciar (sobe server + abre jogo)
#                [C] Configurar idiomas / baixar modelo
#                [M] Ver modelos instalados
#                [S] Subir/parar server
#                [Q] Sair
#
# Server: argostranslate DIRETAMENTE (um processo so, sem libretranslate separado).
# Fala o protocolo do XUnity AutoTranslator:
#   GET  /translate?text=...&from=...&to=...  -> texto traduzido (plain text)
#   POST /translate  (JSON {q/source, target}) -> {translatedText}  (compat LibreTranslate)
#   GET  /health  -> 200 (healthcheck)
#   GET  /?text=...&from=...&to=... -> compatibilidade com configs antigas
#
# Uso:
#   python uat_unity.py            # menu assistente (dev)
#   python uat_unity.py __server__ # sobe o server (bloqueia) - usado pelo .exe buildado
#
import os
import sys
import json
import time
import socket
import threading
import shutil
import subprocess
import zipfile
import hashlib
import struct
import tempfile
import urllib.request
import urllib.parse
import urllib.error
import http.server
import re as _re

# Jogos japoneses/chineses frequentemente vivem em caminhos que nao cabem na
# pagina de codigo legada do CMD. Nunca deixe um print derrubar o launcher.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    except (AttributeError, OSError):
        pass

# =========================================================================
# PATHS  (UAT-UNITY vive DENTRO do jogo -> GAME_DIR = pai de UAT_DIR)
# =========================================================================
FROZEN = bool(getattr(sys, 'frozen', False))
if FROZEN:
    SELF_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SELF_DIR = os.path.dirname(os.path.abspath(__file__))
UAT_DIR = SELF_DIR

_LAUNCHER_EXES = {
    'lt.exe', 'uat-unity.exe', 'uat_unity.exe', 'python.exe', 'pythonw.exe',
    'unitycrashhandler32.exe', 'unitycrashhandler64.exe', 'bepinex.preloader.exe',
    'steam.exe', 'steamservice.exe', 'unins000.exe', 'uninstall.exe',
}

def _unity_root_score(path):
    """Pontua uma pasta sem alterar nada; evita confundir a pasta do pack com o jogo."""
    try:
        names = os.listdir(path)
    except OSError:
        return 0
    lowered = {name.lower(): name for name in names}
    data_dirs = [name for name in names
                 if name.lower().endswith('_data') and os.path.isdir(os.path.join(path, name))]
    game_exes = [name for name in names
                 if name.lower().endswith('.exe') and name.lower() not in _LAUNCHER_EXES]
    score = 0
    if data_dirs:
        score += 5
    if game_exes:
        score += 2
    if 'unityplayer.dll' in lowered:
        score += 4
    if 'gameassembly.dll' in lowered:
        score += 3
    if 'monobleedingedge' in lowered:
        score += 2
    for exe in game_exes:
        if any(d.lower() == os.path.splitext(exe)[0].lower() + '_data' for d in data_dirs):
            score += 5
            break
    return score

def _find_game_dir(base):
    override = os.environ.get('UAT_GAME_DIR', '').strip()
    if override:
        return os.path.abspath(override)
    candidates = []
    current = os.path.abspath(base)
    for _ in range(5):
        if current not in candidates:
            candidates.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    ranked = sorted(((_unity_root_score(path), -index, path)
                     for index, path in enumerate(candidates)), reverse=True)
    if ranked and ranked[0][0] >= 7:
        return ranked[0][2]
    # Layout documentado: <jogo>/uat-unity/lt.exe. Sem marcadores, nao inventa
    # um jogo acima de uma distribuicao colocada em outro lugar.
    if os.path.basename(base).lower().replace('_', '-') in ('uat-unity', 'uatunity'):
        return os.path.dirname(base)
    return base

GAME_DIR = _find_game_dir(UAT_DIR)
# O desktop usa uma biblioteca universal compartilhada entre Unity e Ren'Py.
# O pack portátil continua usando sua própria pasta quando a variável não existe.
PORTABLE_MODELS_DIR = os.path.abspath(
    os.environ.get('UAT_MODELS_DIR', '').strip() or os.path.join(UAT_DIR, 'models'))

def _is_ascii_path(path):
    try:
        os.path.abspath(path).encode('ascii')
        return True
    except UnicodeEncodeError:
        return False

def _runtime_models_dir(portable_dir):
    """Da aos componentes nativos do Argos um caminho ASCII no Windows.

    SentencePiece/CTranslate2 podem relatar NOT_FOUND para um arquivo existente
    quando qualquer pasta ancestral contem caracteres japoneses/chineses. Uma
    junction ASCII preserva os modelos dentro do pack sem duplicar dezenas de MB.
    """
    os.makedirs(portable_dir, exist_ok=True)
    if os.name != 'nt' or _is_ascii_path(portable_dir):
        return portable_dir

    digest = hashlib.sha256(os.path.normcase(os.path.abspath(portable_dir)).encode('utf-8')).hexdigest()[:16]
    roots = [os.environ.get('LOCALAPPDATA'), tempfile.gettempdir()]
    for root in roots:
        if not root or not _is_ascii_path(root):
            continue
        alias_parent = os.path.join(root, 'UAT-Unity', 'model-links', digest)
        alias = os.path.join(alias_parent, 'models')
        try:
            os.makedirs(alias_parent, exist_ok=True)
            if os.path.isdir(alias):
                try:
                    if os.path.samefile(alias, portable_dir):
                        return alias
                except OSError:
                    pass
                continue
            result = subprocess.run(
                ['cmd.exe', '/d', '/c', 'mklink', '/J', alias, portable_dir],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                check=False,
            )
            if result.returncode == 0 and os.path.isdir(alias):
                return alias
        except OSError:
            continue
    # Ultimo recurso: manter o caminho portatil. O validador do modelo exibira
    # um erro acionavel caso a biblioteca nativa dessa maquina rejeite Unicode.
    return portable_dir

MODELS_DIR = _runtime_models_dir(PORTABLE_MODELS_DIR)
PACKAGES_DIR = os.path.join(MODELS_DIR, 'argos-translate', 'packages')
LOGS_DIR = os.path.join(UAT_DIR, 'Logs')
CACHE_ZIP_DIR = os.path.join(UAT_DIR, '_cache_downloads')
CONFIG_PATH = os.path.join(UAT_DIR, 'unity_uat_config.json')
SERVER_LOG = os.path.join(LOGS_DIR, 'uat_server.log')
DEFAULT_PORT = 5001                            # XUnity aponta aqui (CustomTranslate)

os.makedirs(PACKAGES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(CACHE_ZIP_DIR, exist_ok=True)
# argostranslate le modelos desses env vars -> setar ANTES do import
os.environ['XDG_DATA_HOME'] = MODELS_DIR
os.environ['XDG_CONFIG_HOME'] = os.path.join(MODELS_DIR, 'config')
os.environ['XDG_CACHE_HOME'] = os.path.join(MODELS_DIR, 'cache')
os.environ['ARGOS_PACKAGES_DIR'] = PACKAGES_DIR
os.environ.setdefault('ARGOS_DEVICE_TYPE', 'cpu')
try:
    from minisbd import models as _msbd
    _msbd.cache_dir = os.path.join(MODELS_DIR, 'minisbd')
except Exception:
    pass
import argostranslate.package as _apackage
import argostranslate.translate as _atranslate
try:
    from langdetect import DetectorFactory as _DetectorFactory
    from langdetect import detect_langs as _detect_langs
    _DetectorFactory.seed = 0
except Exception:
    _detect_langs = None

# =========================================================================
# DOWNLOADS DO GITHUB (BepInEx + XUnity)
# =========================================================================
DEPENDENCIES = {
    ('Mono', 'x64'): {
        'bepinex': ('BepInEx 5.4.23.5 Mono x64',
            'https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.5/BepInEx_win_x64_5.4.23.5.zip',
            '82f9878551030f54657792c0740d9d51a09500eeae1fba21106b0c441e6732c4'),
        'xunity': ('XUnity AutoTranslator 5.6.1 Mono',
            'https://github.com/bbepis/XUnity.AutoTranslator/releases/download/v5.6.1/XUnity.AutoTranslator-BepInEx-5.6.1.zip',
            'fbb7d1bbe2c7cc168da6dccbc500fb74786a85a548f52495c8a1592ac46407f5'),
    },
    ('Mono', 'x86'): {
        'bepinex': ('BepInEx 5.4.23.5 Mono x86',
            'https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.5/BepInEx_win_x86_5.4.23.5.zip',
            '37651c79e40d6f909572a4f461ac25350bb3ef8fe7fbd29f1aa8791a33b84c82'),
        'xunity': ('XUnity AutoTranslator 5.6.1 Mono',
            'https://github.com/bbepis/XUnity.AutoTranslator/releases/download/v5.6.1/XUnity.AutoTranslator-BepInEx-5.6.1.zip',
            'fbb7d1bbe2c7cc168da6dccbc500fb74786a85a548f52495c8a1592ac46407f5'),
    },
    ('IL2CPP', 'x64'): {
        'bepinex': ('BepInEx 6.0.0-pre.2 IL2CPP x64',
            'https://github.com/BepInEx/BepInEx/releases/download/v6.0.0-pre.2/BepInEx-Unity.IL2CPP-win-x64-6.0.0-pre.2.zip',
            '616ec7eb06cf11b2a0000e8fcef04d1b12bb58e84a2e0bdac9523234fc193ceb'),
        'xunity': ('XUnity AutoTranslator 5.6.1 IL2CPP',
            'https://github.com/bbepis/XUnity.AutoTranslator/releases/download/v5.6.1/XUnity.AutoTranslator-BepInEx-IL2CPP-5.6.1.zip',
            '9d6b26e9d4957459bdb64b6d4852edb39cd5e8d31c28e0a157cefd6510ada811'),
    },
    ('IL2CPP', 'x86'): {
        'bepinex': ('BepInEx 6.0.0-pre.2 IL2CPP x86',
            'https://github.com/BepInEx/BepInEx/releases/download/v6.0.0-pre.2/BepInEx-Unity.IL2CPP-win-x86-6.0.0-pre.2.zip',
            'cfef3a1e946dac5db8b9de4de1a922f47584dd775da32863f36762fbaad80f19'),
        'xunity': ('XUnity AutoTranslator 5.6.1 IL2CPP',
            'https://github.com/bbepis/XUnity.AutoTranslator/releases/download/v5.6.1/XUnity.AutoTranslator-BepInEx-IL2CPP-5.6.1.zip',
            '9d6b26e9d4957459bdb64b6d4852edb39cd5e8d31c28e0a157cefd6510ada811'),
    },
}

# =========================================================================
# CONFIG POR JOGO  (unity_uat_config.json dentro de UAT-UNITY/)
# =========================================================================
def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg.setdefault('source_language', 'en')
    cfg.setdefault('target_language', 'pt-BR')
    cfg.setdefault('languages_configured', False)
    cfg.setdefault('server', {'port': DEFAULT_PORT})
    return cfg

def save_config(cfg):
    cfg = dict(cfg)
    cfg.setdefault('server', {'port': DEFAULT_PORT})
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def server_port():
    return int(load_config().get('server', {}).get('port', DEFAULT_PORT))

# =========================================================================
# GERENCIAMENTO DE MODELOS ARGOS
# =========================================================================
def _argos_code(code):
    '''Codigo Argos/argostranslate. pt-BR/pb -> pb ; pt-PT/pt -> pt.'''
    v = str(code or '').strip().lower()
    if v in ('pt-br', 'pt_br', 'pb', 'brasil', 'br'):
        return 'pb'
    if v in ('pt-pt', 'pt_pt'):
        return 'pt'
    if v == 'pt':
        return 'pt'
    return v.split('-')[0] if v else 'en'

def _config_code(code):
    '''Codigo pro config do XUnity: pb -> pt-BR ; pt -> pt.'''
    if code == 'pb':
        return 'pt-BR'
    if code == 'pt':
        return 'pt'
    return code

def installed_models():
    '''dict {(src,tgt): {from,to,version}} dos pacotes Argos instalados.'''
    out = {}
    try:
        for pkg in _apackage.get_installed_packages():
            s = _argos_code(getattr(pkg, 'from_code', ''))
            t = _argos_code(getattr(pkg, 'to_code', ''))
            if s and t and _package_complete(pkg):
                out[(s, t)] = {'from': getattr(pkg, 'from_name', s),
                               'to': getattr(pkg, 'to_name', t),
                               'version': str(getattr(pkg, 'package_version', '?'))}
    except Exception:
        pass
    return out

def _package_complete(pkg):
    """Valida os componentes comuns aos formatos Argos antigos e atuais."""
    root = str(getattr(pkg, 'package_path', '') or '')
    if not root or not os.path.isdir(root):
        return False
    required = (
        os.path.join(root, 'metadata.json'),
        os.path.join(root, 'model', 'model.bin'),
    )
    tokenizer = (
        os.path.join(root, 'sentencepiece.model'),
        os.path.join(root, 'bpe.model'),
    )
    return (all(os.path.isfile(path) and os.path.getsize(path) > 0 for path in required)
            and any(os.path.isfile(path) and os.path.getsize(path) > 0
                    for path in tokenizer))

def _quarantine_incomplete_pair(src, tgt):
    """Move pacote quebrado para backup antes de reinstalar pelo Argos."""
    moved = False
    for pkg in list(_apackage.get_installed_packages()):
        if (_argos_code(getattr(pkg, 'from_code', '')),
                _argos_code(getattr(pkg, 'to_code', ''))) != (src, tgt):
            continue
        if _package_complete(pkg):
            continue
        root = str(getattr(pkg, 'package_path', '') or '')
        if not root or not os.path.isdir(root):
            continue
        backup_dir = os.path.join(UAT_DIR, 'Backups', 'models')
        os.makedirs(backup_dir, exist_ok=True)
        name = '{}-incompleto-{}'.format(os.path.basename(root), time.strftime('%Y%m%d-%H%M%S'))
        destination = os.path.join(backup_dir, name)
        suffix = 1
        while os.path.exists(destination):
            destination = os.path.join(backup_dir, name + '-{}'.format(suffix))
            suffix += 1
        shutil.move(root, destination)
        print('[AVISO] Modelo incompleto movido para: {}'.format(destination), flush=True)
        moved = True
    if moved:
        _refresh_argos()
    return moved

def _refresh_argos():
    '''Força recarregar a lista de idiomas instalados no argostranslate.'''
    try:
        _atranslate.installed_languages = _atranslate.get_installed_languages()
    except Exception:
        pass

def available_models(refresh=True):
    '''dict {(src,tgt): pkg} de pares diretos no catalogo Argos.'''
    out = {}
    try:
        if refresh:
            _apackage.update_package_index()
        for pkg in _apackage.get_available_packages():
            s = _argos_code(getattr(pkg, 'from_code', ''))
            t = _argos_code(getattr(pkg, 'to_code', ''))
            if s and t and s != t:
                out[(s, t)] = pkg
    except Exception:
        pass
    return out

def _language_names(packages):
    names = {'en': 'English', 'pt': 'Portugues', 'es': 'Spanish', 'fr': 'French',
             'de': 'German', 'ja': 'Japanese', 'ko': 'Korean', 'zh': 'Chinese',
             'it': 'Italian', 'ru': 'Russian'}
    for (s, t), pkg in packages.items():
        names[s] = getattr(pkg, 'from_name', None) or names.get(s, s)
        names[t] = getattr(pkg, 'to_name', None) or names.get(t, t)
    return names

def install_pair(src, tgt):
    '''Baixa + instala modelo Argos para o par (argos codes).'''
    src, tgt = _argos_code(src), _argos_code(tgt)
    if (src, tgt) in installed_models():
        return True
    _quarantine_incomplete_pair(src, tgt)
    av = available_models(refresh=True)
    pkg = av.get((src, tgt))
    if pkg is None:
        print('[ERRO] Nenhum modelo direto disponivel para {} -> {}.'.format(src, tgt), flush=True)
        return False
    print('[1/2] Baixando modelo {} -> {}...'.format(src, tgt), flush=True)
    try:
        downloaded = pkg.download()
    except TypeError:
        downloaded = pkg.download(None)
    except Exception as e:
        print('[ERRO] download: {}'.format(e), flush=True)
        return False
    print('[2/2] Instalando modelo...', flush=True)
    try:
        _apackage.install_from_path(downloaded)
    except Exception as e:
        print('[ERRO] install: {}'.format(e), flush=True)
        return False
    _refresh_argos()
    ok = (src, tgt) in installed_models()
    print(('OK' if ok else 'FALHOU') + ' instalar modelo.', flush=True)
    return ok

def validate_pair(src, tgt):
    """Carrega o modelo e aquece o segmentador; baixa recursos auxiliares se faltarem."""
    src, tgt = _argos_code(src), _argos_code(tgt)
    if (src, tgt) not in installed_models():
        return False
    print('[validacao] Preparando motor {} -> {}...'.format(src, tgt), flush=True)
    try:
        _refresh_argos()
        languages = {language.code: language for language in _atranslate.get_installed_languages()}
        source = languages.get(src)
        target = languages.get(tgt)
        translation = source.get_translation(target) if source and target else None
        if translation is None:
            raise RuntimeError('Argos nao criou o tradutor para o par')
        translation.translate('UAT translation test')
        print('[OK] Modelo e recursos auxiliares prontos.', flush=True)
        return True
    except Exception as error:
        print('[ERRO] Falha ao validar {} -> {}: {}'.format(src, tgt, error), flush=True)
        return False

def cache_size():
    total = 0
    for dp, _d, fs in os.walk(MODELS_DIR):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except Exception:
                pass
    return total

def cache_path():
    return MODELS_DIR

# =========================================================================
# TRADUCAO (backend Argos direto)
# =========================================================================
_translate_lock = threading.Lock()

def _ensure_pair_loaded(src, tgt):
    src, tgt = _argos_code(src), _argos_code(tgt)
    if (src, tgt) not in installed_models():
        install_pair(src, tgt)
        _refresh_argos()
    return (src, tgt) in installed_models()

def _translate_pair(text, source, target):
    """Traduz um par Argos já selecionado; informa se a etapa foi concluída."""
    if not _ensure_pair_loaded(source, target):
        _log('[translate] modelo ausente: {} -> {}'.format(source, target))
        return False, text
    _refresh_argos()
    langs = {language.code: language for language in _atranslate.get_installed_languages()}
    translation = langs.get(source).get_translation(langs.get(target)) if langs.get(source) and langs.get(target) else None
    if translation is None:
        _log('[translate] par indisponível: {} -> {}'.format(source, target))
        return False, text
    return True, translation.translate(text)

def translate_text(text, from_code, to_code):
    '''Traduz diretamente ou em cadeia, sempre no mesmo processo Argos.'''
    if not text:
        return ''
    cfg = load_config()
    source = _argos_code(cfg.get('source_language', 'en') if from_code in ('auto', '', None) else from_code)
    target = _argos_code(to_code)
    try:
        with _translate_lock:
            if cfg.get('flow_mode') == 'chain':
                middle = _argos_code(cfg.get('intermediate_language', 'en'))
                first_ok, intermediate = _translate_pair(text, source, middle)
                if not first_ok:
                    return text
                second_ok, translated = _translate_pair(intermediate, middle, target)
                return translated if second_ok else text
            ok, translated = _translate_pair(text, source, target)
            return translated if ok else text
    except Exception as error:
        _log('[translate] erro: {}'.format(error))
        return text

# =========================================================================
# LOG
# =========================================================================
def _log(msg):
    try:
        ts = time.strftime('%H:%M:%S')
        line = '[{}] {}'.format(ts, msg)
        with open(SERVER_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
    print(msg, flush=True)

# =========================================================================
# SERVIDOR HTTP (XUnity CustomTranslate + compat LibreTranslate)
# =========================================================================
class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'UAT-Unity/1.0'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype='text/plain; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', '/translate'):
            q = urllib.parse.parse_qs(parsed.query)
            text = q.get('text', [None])[0]
            frm = q.get('from', ['auto'])[0]
            to = q.get('to', [None])[0]
            # O XUnity CustomTranslate acrescenta os parametros GET diretamente
            # a URL configurada. Aceitar a raiz com parametros corrige instalacoes
            # antigas que receberam apenas http://127.0.0.1:PORT como Url.
            if parsed.path == '/' and not text and not to:
                self._send(200, 'ok')
                return
            if not text or not to:
                self._send(400, 'Missing text or target language')
                return
            translated = translate_text(text, frm, to)
            _log('[TRAD] {} -> {} | {} => {}'.format(
                frm, to, str(text).replace('\n', ' ')[:180],
                str(translated).replace('\n', ' ')[:180]))
            self._send(200, translated)
            return
        if parsed.path == '/health':
            self._send(200, 'ok')
            return
        self._send(404, 'Not Found')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != '/translate':
            self._send(404, 'Not Found')
            return
        length = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(length) if length else b''
        try:
            payload = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            payload = {}
        if not payload:
            ctype = self.headers.get('Content-Type', '')
            if 'application/x-www-form-urlencoded' in ctype:
                payload = urllib.parse.parse_qs(raw.decode('utf-8'))
                payload = {k: v[0] for k, v in payload.items()}
        text = payload.get('q') or payload.get('text')
        frm = payload.get('source') or payload.get('from') or 'auto'
        to = payload.get('target') or payload.get('to')
        if not text or not to:
            self._send(400, json.dumps({'error': 'Missing text or target language'}), ctype='application/json')
            return
        translated = translate_text(text, frm, to)
        _log('[TRAD] {} -> {} | {} => {}'.format(
            frm, to, str(text).replace('\n', ' ')[:180],
            str(translated).replace('\n', ' ')[:180]))
        self._send(200, json.dumps({'translatedText': translated}), ctype='application/json')

class _Srv(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

_server = None
_server_lock = threading.Lock()

def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0

def server_ready(timeout=1.5):
    port = server_port()
    try:
        urllib.request.urlopen('http://127.0.0.1:{}/health'.format(port), timeout=timeout).close()
        return True
    except Exception:
        return False

def start_server(cb=None):
    global _server
    port = server_port()
    with _server_lock:
        if _server is not None:
            return True
        if _port_in_use(port):
            if server_ready():
                _log('Servidor UAT ja responde na porta {}.'.format(port))
                if cb:
                    cb()
                return True
            _log('ERRO: porta {} ocupada por outro processo.'.format(port))
            return False
        _server = _Srv(('127.0.0.1', port), _Handler)
        threading.Thread(target=_server.serve_forever, daemon=True).start()
        _log('Servidor UAT ouvindo em 127.0.0.1:{}.'.format(port))
        if cb:
            threading.Thread(target=cb, daemon=True).start()
        return True

def stop_server():
    global _server
    with _server_lock:
        if _server is not None:
            try:
                _server.shutdown()
            except Exception:
                pass
            try:
                _server.server_close()
            except Exception:
                pass
            _server = None
            _log('Servidor parado.')

def _run_server_forever():
    '''Modo __server__: sobe e fica de pe (para build exe / isolado).'''
    start_server()
    _log('Modo servidor. Ctrl+C para parar. Porta {}.'.format(server_port()))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server()

# =========================================================================
# DETECCAO DE JOGO / RUNTIME
# =========================================================================
def game_name():
    return os.path.basename(GAME_DIR.rstrip(os.sep)) or 'jogo'

def _candidate_game_exes():
    try:
        exes = [os.path.join(GAME_DIR, name) for name in os.listdir(GAME_DIR)
                if name.lower().endswith('.exe') and name.lower() not in _LAUNCHER_EXES]
    except OSError:
        return []
    def rank(path):
        stem = os.path.splitext(os.path.basename(path))[0]
        matching_data = os.path.isdir(os.path.join(GAME_DIR, stem + '_Data'))
        suspicious = any(word in stem.lower() for word in
                         ('crash', 'unins', 'uninstall', 'launcher', 'reporter', 'server'))
        return (not matching_data, suspicious, len(stem), stem.lower())
    return sorted(exes, key=rank)

def find_game_exe():
    exes = _candidate_game_exes()
    return exes[0] if exes else None

def _data_dir_for_exe(exe):
    if exe:
        exact = os.path.join(GAME_DIR, os.path.splitext(os.path.basename(exe))[0] + '_Data')
        if os.path.isdir(exact):
            return exact
    try:
        candidates = [os.path.join(GAME_DIR, name) for name in os.listdir(GAME_DIR)
                      if name.lower().endswith('_data') and os.path.isdir(os.path.join(GAME_DIR, name))]
    except OSError:
        candidates = []
    return sorted(candidates)[0] if candidates else None

def _pe_arch(path):
    """Le somente o cabecalho PE; retorna x86, x64 ou Unknown."""
    if not path or not os.path.isfile(path):
        return 'Unknown'
    try:
        with open(path, 'rb') as f:
            if f.read(2) != b'MZ':
                return 'Unknown'
            f.seek(0x3c)
            pe_offset = struct.unpack('<I', f.read(4))[0]
            f.seek(pe_offset)
            if f.read(4) != b'PE\x00\x00':
                return 'Unknown'
            machine = struct.unpack('<H', f.read(2))[0]
        return {0x014c: 'x86', 0x8664: 'x64', 0xaa64: 'arm64'}.get(machine, 'Unknown')
    except (OSError, EOFError, struct.error):
        return 'Unknown'

def _unity_version(data_dir):
    if not data_dir:
        return None
    for name in ('globalgamemanagers', 'data.unity3d'):
        path = os.path.join(data_dir, name)
        try:
            with open(path, 'rb') as f:
                sample = f.read(2 * 1024 * 1024)
            match = _re.search(rb'(?<!\d)(20\d{2}|[3-9])\.\d+\.\d+[abfp]\d+(?!\d)', sample)
            if match:
                return match.group(0).decode('ascii')
        except OSError:
            continue
    return None

def detect_game():
    exe = find_game_exe()
    data_dir = _data_dir_for_exe(exe)
    managed = os.path.join(data_dir, 'Managed') if data_dir else ''
    assembly = os.path.join(managed, 'Assembly-CSharp.dll') if managed else ''
    metadata = os.path.join(data_dir, 'il2cpp_data', 'Metadata', 'global-metadata.dat') if data_dir else ''
    gameassembly = os.path.join(GAME_DIR, 'GameAssembly.dll')
    mono_dir = os.path.join(GAME_DIR, 'MonoBleedingEdge')

    mono_signals = [os.path.isfile(assembly), os.path.isdir(mono_dir)]
    il2cpp_signals = [os.path.isfile(gameassembly), os.path.isfile(metadata)]
    if all(il2cpp_signals):
        runtime = 'IL2CPP'
        confidence = 'alta'
    elif all(mono_signals):
        runtime = 'Mono'
        confidence = 'alta'
    elif any(il2cpp_signals) and not any(mono_signals):
        runtime = 'IL2CPP'
        confidence = 'media'
    elif any(mono_signals) and not any(il2cpp_signals):
        runtime = 'Mono'
        confidence = 'media'
    else:
        runtime = 'Unknown'
        confidence = 'baixa'

    arch_target = gameassembly if runtime == 'IL2CPP' and os.path.isfile(gameassembly) else exe
    return {
        'valid': bool(exe and data_dir and _unity_root_score(GAME_DIR) >= 7),
        'game_dir': GAME_DIR,
        'exe': exe,
        'data_dir': data_dir,
        'runtime': runtime,
        'architecture': _pe_arch(arch_target),
        'unity_version': _unity_version(data_dir),
        'confidence': confidence,
        'signals': {
            'assembly_csharp': bool(assembly and os.path.isfile(assembly)),
            'mono_bleeding_edge': os.path.isdir(mono_dir),
            'game_assembly': os.path.isfile(gameassembly),
            'global_metadata': bool(metadata and os.path.isfile(metadata)),
        },
    }

def detect_runtime():
    info = detect_game()
    return info['runtime'], info['signals']['mono_bleeding_edge']

def _xunity_dlls():
    # Nao usar glob: nomes de jogos frequentemente contem [] e outros caracteres
    # que glob interpreta como metacaracteres.
    found = []
    root_dir = os.path.join(GAME_DIR, 'BepInEx')
    try:
        for root, _dirs, files in os.walk(root_dir):
            for name in files:
                lowered = name.lower()
                if lowered.endswith('.dll') and 'autotranslator' in lowered:
                    found.append(os.path.join(root, name))
    except OSError:
        pass
    return found

def _existing_bepinex_runtime():
    core = os.path.join(GAME_DIR, 'BepInEx', 'core')
    if os.path.isfile(os.path.join(core, 'BepInEx.Unity.IL2CPP.dll')):
        return 'IL2CPP'
    if os.path.isfile(os.path.join(core, 'BepInEx.dll')):
        return 'Mono'
    if os.path.isfile(os.path.join(core, 'BepInEx.Unity.Mono.dll')):
        return 'Mono'
    return None

def installation_status(info=None):
    info = info or detect_game()
    runtime = info.get('runtime')
    existing = _existing_bepinex_runtime()
    return {
        'bepinex': bool(existing),
        'bepinex_runtime': existing,
        'runtime_match': not existing or runtime == 'Unknown' or existing == runtime,
        'xunity': bool(_xunity_dlls()),
        'config': os.path.isfile(os.path.join(GAME_DIR, 'BepInEx', 'config', 'AutoTranslatorConfig.ini')),
    }

def is_first_run():
    status = installation_status()
    return not (status['bepinex'] and status['xunity'] and status['runtime_match'])

# =========================================================================
# DOWNLOAD + EXTRACAO
# =========================================================================
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()

def _valid_download(path, expected_sha256=None):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return False
    try:
        with zipfile.ZipFile(path, 'r') as z:
            if z.testzip() is not None:
                return False
    except (OSError, zipfile.BadZipFile):
        return False
    return not expected_sha256 or _sha256(path).lower() == expected_sha256.lower()

def download_file(url, dest, label='arquivo', expected_sha256=None):
    if _valid_download(dest, expected_sha256):
        print('[cache] {} ja baixado e valido.'.format(label), flush=True)
        return dest
    part = dest + '.part'
    last_error = None
    for attempt in range(1, 4):
        try:
            if os.path.exists(part):
                os.remove(part)
            req = urllib.request.Request(url, headers={'User-Agent': 'UAT-Unity/2.0'})
            print('[download {}/3] {} ...'.format(attempt, label), flush=True)
            with urllib.request.urlopen(req, timeout=600) as response:
                total = int(response.headers.get('Content-Length', 0) or 0)
                got = 0
                last_percent = -5
                with open(part, 'wb') as f:
                    while True:
                        block = response.read(131072)
                        if not block:
                            break
                        f.write(block)
                        got += len(block)
                        if total:
                            percent = got * 100 // total
                            if percent >= last_percent + 5 or percent == 100:
                                sys.stdout.write('\r  {} {}%'.format(label, percent))
                                sys.stdout.flush()
                                last_percent = percent
            if total and got != total:
                raise IOError('download incompleto: {} de {} bytes'.format(got, total))
            if expected_sha256 and _sha256(part).lower() != expected_sha256.lower():
                raise IOError('SHA-256 invalido para {}'.format(label))
            if not _valid_download(part, expected_sha256):
                raise IOError('ZIP invalido para {}'.format(label))
            os.replace(part, dest)
            print('\n[OK] {} ({})'.format(label, _fmt_size(got)), flush=True)
            return dest
        except Exception as error:
            last_error = error
            try:
                os.remove(part)
            except OSError:
                pass
            if attempt < 3:
                print('[AVISO] {}. Tentando novamente...'.format(error), flush=True)
                time.sleep(attempt)
    raise RuntimeError('falha ao baixar {}: {}'.format(label, last_error))

def _extract_safe(zip_path, dest):
    """Extrai ZIP impedindo caminhos que escapem do destino."""
    root = os.path.abspath(dest)
    with zipfile.ZipFile(zip_path, 'r') as z:
        for member in z.infolist():
            target = os.path.abspath(os.path.join(root, member.filename))
            try:
                safe = os.path.commonpath([root, target]) == root
            except ValueError:
                safe = False
            if not safe:
                raise RuntimeError('caminho inseguro no ZIP: {}'.format(member.filename))
        z.extractall(root)

def _merge_tree(source, destination):
    os.makedirs(destination, exist_ok=True)
    for name in os.listdir(source):
        src = os.path.join(source, name)
        dst = os.path.join(destination, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

# =========================================================================
# AutoTranslatorConfig.ini  (minimal -> XUnity expande no primeiro run)
# =========================================================================
MINIMAL_AT_INI = (
    '[Service]\n'
    'Endpoint=CustomTranslate\n'
    'FallbackEndpoint=GoogleTranslateV2\n'
    '\n'
    '[General]\n'
    'Language=pt-BR\n'
    'FromLanguage=en\n'
    '\n'
    '[Custom]\n'
    'Url=http://127.0.0.1:5001/translate\n'
    'EnableShortDelay=False\n'
    'DisableSpamChecks=False\n'
    '\n'
    '[Migrations]\n'
    'Enable=True\n'
    'Tag=5.6.1\n'
)

def _set_ini(content, section, key, value):
    lines = content.split('\n')
    out = []
    in_sec = False
    done = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            in_sec = (stripped == '[' + section + ']')
            out.append(line)
            continue
        if in_sec and not done and '=' in stripped and stripped.split('=', 1)[0].strip() == key:
            out.append('{}={}'.format(key, value))
            done = True
            continue
        out.append(line)
    content = '\n'.join(out)
    if not done:
        content = content.rstrip() + '\n\n[' + section + ']\n' + '{}{}'.format(key, '=' + value + '\n')
    return content

def patch_autotranslator_ini(src, tgt):
    cfg_dir = os.path.join(GAME_DIR, 'BepInEx', 'config')
    os.makedirs(cfg_dir, exist_ok=True)
    ini = os.path.join(cfg_dir, 'AutoTranslatorConfig.ini')
    content = MINIMAL_AT_INI if not os.path.exists(ini) else open(ini, 'r', encoding='utf-8').read()
    content = _set_ini(content, 'General', 'Language', _config_code(_argos_code(tgt)))
    content = _set_ini(content, 'General', 'FromLanguage', _config_code(_argos_code(src)))
    content = _set_ini(content, 'Service', 'Endpoint', 'CustomTranslate')
    content = _set_ini(content, 'Service', 'FallbackEndpoint', 'GoogleTranslateV2')
    content = _set_ini(content, 'Custom', 'Url', 'http://127.0.0.1:{}/translate'.format(server_port()))
    cfg = load_config()
    flow = [_argos_code(src)]
    if cfg.get('flow_mode') == 'chain':
        flow.append(_argos_code(cfg.get('intermediate_language', 'en')))
    flow.append(_argos_code(tgt))
    output = r'Translation\SFTranslator\{}\Text\_AutoGeneratedTranslations.txt'.format('_'.join(flow))
    content = _set_ini(content, 'Files', 'OutputFile', output)
    with open(ini, 'w', encoding='utf-8') as f:
        f.write(content)
    return ini

def write_start_bat():
    '''Cria start_translation.bat na raiz do jogo, com layout plano ou em subpasta.'''
    bat = os.path.join(GAME_DIR, 'start_translation.bat')
    try:
        exe_rel = os.path.relpath(os.path.join(UAT_DIR, 'lt.exe'), GAME_DIR).replace('/', '\\')
        script_rel = os.path.relpath(os.path.join(UAT_DIR, 'uat_unity.py'), GAME_DIR).replace('/', '\\')
        exe_cmd = '%~dp0' + exe_rel
        script_cmd = '%~dp0' + script_rel
    except ValueError:
        # Modo de desenvolvimento com UAT_GAME_DIR em outra unidade.
        exe_cmd = os.path.join(UAT_DIR, 'lt.exe')
        script_cmd = os.path.join(UAT_DIR, 'uat_unity.py')
    lines = [
        '@echo off',
        'cd /d "%~dp0"',
        'if exist "' + exe_cmd + '" (',
        '    "' + exe_cmd + '"',
        ') else (',
        '    python "' + script_cmd + '"',
        ')',
        '',
    ]
    with open(bat, 'w', encoding='utf-8') as f:
        f.write('\r\n'.join(lines))
    return bat

def install_bepinex_xunity(runtime=None, architecture=None, on_step=None):
    info = detect_game()
    detected_runtime = info['runtime']
    detected_architecture = info['architecture']
    runtime = runtime or detected_runtime
    architecture = architecture or detected_architecture
    if not info['valid']:
        raise RuntimeError('a pasta detectada nao parece ser a raiz de um jogo Unity: ' + GAME_DIR)
    if runtime not in ('Mono', 'IL2CPP'):
        raise RuntimeError('runtime Unity ambiguo; use o diagnostico antes de instalar')
    if architecture not in ('x86', 'x64'):
        raise RuntimeError('arquitetura nao suportada/detectada: {}'.format(architecture))
    if detected_runtime != 'Unknown' and runtime != detected_runtime:
        raise RuntimeError('runtime pedido ({}) difere do detectado ({})'.format(
            runtime, detected_runtime))
    if detected_architecture in ('x86', 'x64') and architecture != detected_architecture:
        raise RuntimeError('arquitetura pedida ({}) difere da detectada ({})'.format(
            architecture, detected_architecture))
    manifest = DEPENDENCIES.get((runtime, architecture))
    if not manifest:
        raise RuntimeError('sem modulo para {} {}'.format(runtime, architecture))
    status = installation_status(info)
    if status['bepinex'] and not status['runtime_match']:
        raise RuntimeError('BepInEx {} ja instalado, mas o jogo foi detectado como {}. '
                           'Remova/repare conscientemente antes de continuar.'.format(
                               status['bepinex_runtime'], runtime))
    if on_step:
        on_step(1, 'Jogo detectado: {} {}'.format(runtime, architecture))
    bep_label, bep_url, bep_hash = manifest['bepinex']
    xu_label, xu_url, xu_hash = manifest['xunity']
    bep_zip = os.path.join(CACHE_ZIP_DIR, os.path.basename(bep_url))
    xu_zip = os.path.join(CACHE_ZIP_DIR, os.path.basename(xu_url))
    if on_step:
        on_step(2, 'Baixando BepInEx...')
    download_file(bep_url, bep_zip, bep_label, bep_hash)
    if on_step:
        on_step(3, 'Baixando XUnity AutoTranslator...')
    download_file(xu_url, xu_zip, xu_label, xu_hash)
    if on_step:
        on_step(4, 'Validando e instalando no jogo...')
    stage = tempfile.mkdtemp(prefix='uat-install-', dir=CACHE_ZIP_DIR)
    try:
        bep_stage = os.path.join(stage, 'bepinex')
        xu_stage = os.path.join(stage, 'xunity')
        os.makedirs(bep_stage)
        os.makedirs(xu_stage)
        _extract_safe(bep_zip, bep_stage)
        _extract_safe(xu_zip, xu_stage)
        ini_path = os.path.join(GAME_DIR, 'BepInEx', 'config', 'AutoTranslatorConfig.ini')
        if os.path.isfile(ini_path):
            backup_dir = os.path.join(UAT_DIR, 'Backups')
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(ini_path, os.path.join(
                backup_dir, 'AutoTranslatorConfig-{}.ini'.format(time.strftime('%Y%m%d-%H%M%S'))))
        _merge_tree(bep_stage, GAME_DIR)
        _merge_tree(xu_stage, GAME_DIR)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    cfg = load_config()
    cfg['installation'] = {
        'runtime': runtime,
        'architecture': architecture,
        'bepinex': bep_label,
        'xunity': xu_label,
        'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    save_config(cfg)
    ini = patch_autotranslator_ini(cfg.get('source_language', 'en'), cfg.get('target_language', 'pt-BR'))
    _log('AutoTranslatorConfig.ini: {}'.format(ini))
    write_start_bat()
    final_status = installation_status(info)
    if not final_status['bepinex'] or not final_status['xunity']:
        raise RuntimeError('arquivos extraidos, mas a validacao BepInEx/XUnity falhou')
    if on_step:
        on_step(5, 'Configurado AutoTranslatorConfig.ini + start_translation.bat')
    return True

# =========================================================================
# DETECCAO DO IDIOMA ORIGINAL DO JOGO
# =========================================================================
_LANGUAGE_ALIASES = {
    'arabic': 'ar', 'arabe': 'ar', 'chinese': 'zh', 'chinese simplified': 'zh',
    'simplified chinese': 'zh', 'schinese': 'zh', 'sc': 'zh',
    'chinese traditional': 'zt', 'traditional chinese': 'zt', 'tchinese': 'zt', 'tc': 'zt',
    'english': 'en', 'ingles': 'en', 'french': 'fr', 'francais': 'fr',
    'german': 'de', 'deutsch': 'de', 'italian': 'it', 'italiano': 'it',
    'japanese': 'ja', 'japones': 'ja', 'nihongo': 'ja',
    'korean': 'ko', 'coreano': 'ko', 'portuguese': 'pt', 'portugues': 'pt',
    'brazilian portuguese': 'pb', 'portugues brasileiro': 'pb',
    'russian': 'ru', 'russo': 'ru', 'spanish': 'es', 'espanol': 'es',
}

_DETECTION_EXCLUDED_DIRS = {
    'bepinex', 'mono', 'monobleedingedge', 'uat-unity', 'uat_unity', 'uatunity',
    'models', 'dist', 'build', '_internal', '_cache_downloads', 'backups',
    'translation', '__pycache__',
}

_TEXT_EXTENSIONS = {
    '.cfg', '.config', '.csv', '.ini', '.json', '.loc', '.po', '.properties',
    '.txt', '.xml', '.yaml', '.yml',
}

def _detected_code(value, allowed=None):
    value = str(value or '').strip().strip('"\'').lower().replace('_', '-')
    code = _LANGUAGE_ALIASES.get(value, value)
    aliases = {
        'zh-cn': 'zh', 'zh-hans': 'zh', 'chs': 'zh',
        'zh-tw': 'zt', 'zh-hant': 'zt', 'cht': 'zt',
        'pt-br': 'pb', 'ptb': 'pb', 'br': 'pb',
        'jp': 'ja', 'kr': 'ko', 'ua': 'uk',
    }
    code = aliases.get(code, code.split('-')[0])
    allowed = set(allowed or ())
    if allowed:
        if code == 'pt' and code not in allowed and 'pb' in allowed:
            code = 'pb'
        if code == 'zt' and code not in allowed and 'zh' in allowed:
            code = 'zh'
        if code not in allowed:
            return None
    return code if _re.match(r'^[a-z]{2,3}$', code or '') else None

def _read_text_sample(path, limit=512 * 1024):
    try:
        with open(path, 'rb') as f:
            raw = f.read(limit)
    except OSError:
        return ''
    if not raw:
        return ''
    encodings = ['utf-8-sig']
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')) or raw.count(b'\x00') > len(raw) // 8:
        encodings += ['utf-16', 'utf-16-le', 'utf-16-be']
    encodings += ['cp932', 'latin-1']
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            if text:
                return text
        except (UnicodeDecodeError, LookupError):
            continue
    return ''

def _script_language(text):
    counts = {
        'ja': len(_re.findall(r'[\u3040-\u30ff]', text)),
        'ko': len(_re.findall(r'[\uac00-\ud7af]', text)),
        'zh': len(_re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]', text)),
    }
    if counts['ja'] >= 3:
        return 'ja', min(0.99, 0.82 + counts['ja'] / 500.0)
    if counts['ko'] >= 3:
        return 'ko', min(0.99, 0.82 + counts['ko'] / 500.0)
    if counts['zh'] >= 6:
        return 'zh', min(0.94, 0.72 + counts['zh'] / 800.0)
    return None, 0.0

def _detect_text_language(text, allowed=None):
    text = _re.sub(r'https?://\S+|[A-Za-z]:\\\S+', ' ', str(text or ''))
    text = _re.sub(r'[_{}<>\[\]\\/|=]+', ' ', text)
    if len(_re.findall(r'[^\W\d_]', text, flags=_re.UNICODE)) < 12:
        return None, 0.0
    script_code, script_confidence = _script_language(text)
    script_code = _detected_code(script_code, allowed)
    if script_code:
        return script_code, script_confidence
    if _detect_langs is None:
        return None, 0.0
    try:
        results = _detect_langs(text[:30000])
    except Exception:
        return None, 0.0
    for result in results:
        code = _detected_code(getattr(result, 'lang', ''), allowed)
        if code:
            return code, float(getattr(result, 'prob', 0.0))
    return None, 0.0

def _candidate_game_text_files(limit=100):
    found = []
    for root, dirs, files in os.walk(GAME_DIR):
        dirs[:] = [name for name in dirs if name.lower() not in _DETECTION_EXCLUDED_DIRS]
        for name in files:
            path = os.path.join(root, name)
            if name.lower() in {
                'autotranslatorconfig.ini', 'doorstop_config.ini', 'instalar.txt',
                'unity_uat_config.json', 'uat_config.json',
            }:
                continue
            if os.path.splitext(name)[1].lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            lowered = name.lower()
            priority = 0 if any(token in lowered for token in
                                ('lang', 'locale', 'localiz', 'dialog', 'string', 'scenario', 'text')) else 1
            found.append((priority, path))
            if len(found) >= limit * 2:
                break
        if len(found) >= limit * 2:
            break
    return [path for _, path in sorted(found)[:limit]]

def _explicit_language_setting(paths, allowed=None):
    key = r'(?<![A-Za-z0-9_])(?:current[_ .-]*)?(?:language|locale|lang(?:uage)?[_ .-]*code)'
    pattern = _re.compile(key + r'\s*["\']?\s*[:=]\s*["\']?([A-Za-z]{2,16}(?:[-_ ][A-Za-z]{2,16})?)', _re.I)
    ignored_values = {'c', 'cs', 'csharp', 'neutral', 'auto', 'system', 'default'}
    for path in paths:
        text = _read_text_sample(path, 256 * 1024)
        for value in pattern.findall(text):
            if value.strip().lower() in ignored_values:
                continue
            code = _detected_code(value, allowed)
            if code:
                return code, os.path.relpath(path, GAME_DIR)
    return None, None

def _xunity_displayed_text_sample():
    root = os.path.join(GAME_DIR, 'BepInEx', 'Translation')
    if not os.path.isdir(root):
        return '', 0
    sources = []
    for current, _, files in os.walk(root):
        for name in files:
            if name.lower() != '_autogeneratedtranslations.txt':
                continue
            text = _read_text_sample(os.path.join(current, name), 1024 * 1024)
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(('#', ';', '//')) or '=' not in stripped:
                    continue
                source = stripped.split('=', 1)[0].strip()
                if len(source) >= 2:
                    sources.append(source)
                if len(sources) >= 1200:
                    break
            if len(sources) >= 1200:
                break
        if len(sources) >= 1200:
            break
    return '\n'.join(sources), len(sources)

def _binary_script_sample(limit_bytes=12 * 1024 * 1024):
    info = detect_game()
    data_dir = info.get('data_dir') or ''
    if not os.path.isdir(data_dir):
        return ''
    chunks = []
    consumed = 0
    extensions = {'.assets', '.ress', '.bundle', '.resource', '.resources'}
    for root, _, files in os.walk(data_dir):
        for name in files:
            if os.path.splitext(name)[1].lower() not in extensions:
                continue
            path = os.path.join(root, name)
            try:
                with open(path, 'rb') as f:
                    raw = f.read(min(2 * 1024 * 1024, limit_bytes - consumed))
            except OSError:
                continue
            decoded = raw.decode('utf-8', errors='ignore')
            runs = _re.findall(r'[^\x00-\x1f]{4,}', decoded)
            chunks.extend(run for run in runs if _script_language(run)[0])
            consumed += len(raw)
            if consumed >= limit_bytes:
                return '\n'.join(chunks)
    return '\n'.join(chunks)

def detect_game_language(allowed=None):
    """Sugere o idioma realmente exibido e informa confianca/evidencia."""
    allowed = set(allowed or ())
    paths = _candidate_game_text_files()
    code, relative = _explicit_language_setting(paths, allowed)
    if code:
        return {'code': code, 'confidence': 0.98, 'level': 'alta',
                'evidence': 'configuracao do jogo: {}'.format(relative), 'samples': 1}

    displayed, count = _xunity_displayed_text_sample()
    code, confidence = _detect_text_language(displayed, allowed)
    if code and count >= 3:
        confidence = min(0.99, max(0.78, confidence))
        return {'code': code, 'confidence': confidence,
                'level': 'alta' if confidence >= 0.85 else 'media',
                'evidence': 'textos exibidos capturados pelo XUnity', 'samples': count}

    text_parts = []
    for path in paths:
        sample = _read_text_sample(path)
        if sample:
            text_parts.append(sample[:12000])
        if sum(map(len, text_parts)) >= 60000:
            break
    code, confidence = _detect_text_language('\n'.join(text_parts), allowed)
    if code:
        confidence = min(0.82, max(0.58, confidence))
        return {'code': code, 'confidence': confidence,
                'level': 'media' if confidence >= 0.65 else 'baixa',
                'evidence': 'arquivos de texto e localizacao do jogo', 'samples': len(text_parts)}

    binary = _binary_script_sample()
    code, confidence = _detect_text_language(binary, allowed)
    if code:
        confidence = min(0.76, max(0.58, confidence))
        return {'code': code, 'confidence': confidence,
                'level': 'media' if confidence >= 0.65 else 'baixa',
                'evidence': 'textos encontrados nos assets do Unity', 'samples': 1}

    code, _ = _script_language(game_name() + ' ' + GAME_DIR)
    code = _detected_code(code, allowed)
    if code:
        return {'code': code, 'confidence': 0.52, 'level': 'baixa',
                'evidence': 'nome do jogo/pasta (apenas indicio)', 'samples': 1}
    return None

# =========================================================================
# ASSISTENTE / MENU (launcher interativo)
# =========================================================================
def _prompt(text, default=''):
    try:
        return input(text).strip()
    except EOFError:
        return default

def _fmt_size(n):
    x = float(n)
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if x < 1024 or u == 'TB':
            return '{:.1f} {}'.format(x, u)
        x /= 1024

def _choose_language_grid(title, available, default=None):
    """Seletor paginado em grade para o console interativo do Windows."""
    import msvcrt

    original = list(available)
    filtered = list(available)
    selected = next((index for index, item in enumerate(filtered)
                     if item[0] == default), 0)
    query = ''

    def label(item):
        code, name = item
        suffix = ' *' if code == default else ''
        return '{} ({}){}'.format(name, code, suffix)

    while True:
        width = shutil.get_terminal_size((100, 30)).columns
        columns = 3 if width >= 84 else (2 if width >= 52 else 1)
        cell_width = max(24, min(36, max(24, (width - 4) // columns)))
        rows = 8
        page_size = columns * rows
        if filtered:
            selected = max(0, min(selected, len(filtered) - 1))
        else:
            selected = 0
        page = selected // page_size if filtered else 0
        start = page * page_size
        visible = filtered[start:start + page_size]
        total_pages = max(1, (len(filtered) + page_size - 1) // page_size)

        print('\x1b[2J\x1b[H', end='')
        print('=' * min(width, 100))
        print('  ' + title)
        print('=' * min(width, 100))
        print('  Setas/WASD: navegar   ENTER: selecionar   /: buscar   ESC/Q: voltar')
        if query:
            print("  Filtro: {!r}   Resultados: {}".format(query, len(filtered)))
        else:
            print('  Pagina {}/{}   Opcoes: {}'.format(page + 1, total_pages, len(filtered)))
        print()

        for row in range(rows):
            cells = []
            for column in range(columns):
                local = row * columns + column
                absolute = start + local
                if local >= len(visible):
                    cells.append(' ' * cell_width)
                    continue
                text = label(visible[local]).replace('\n', ' ')[:cell_width - 4]
                marker = '>' if absolute == selected else ' '
                cells.append((' {} {:<{}}'.format(marker, text, cell_width - 3))[:cell_width])
            print(''.join(cells).rstrip())

        if not filtered:
            print('  Nenhum idioma encontrado. Pressione / para buscar novamente.')

        key = msvcrt.getwch()
        if key in ('\x00', '\xe0'):
            extended = msvcrt.getwch()
            key = {'H': 'up', 'P': 'down', 'K': 'left', 'M': 'right',
                   'I': 'pageup', 'Q': 'pagedown'}.get(extended, '')
        else:
            key = key.lower()

        if key in ('\r', '\n') and filtered:
            print()
            return _argos_code(filtered[selected][0])
        if key in ('\x1b', 'q'):
            print()
            return None
        if key in ('/', 'f'):
            print('\nBuscar idioma (nome ou codigo): ', end='', flush=True)
            query = input().strip().lower()
            filtered = [item for item in original if query in label(item).lower()]
            selected = 0
            continue
        if key in ('up', 'w'):
            selected -= columns
        elif key in ('down', 's'):
            selected += columns
        elif key in ('left', 'a'):
            selected -= 1
        elif key in ('right', 'd'):
            selected += 1
        elif key == 'pageup':
            selected -= page_size
        elif key == 'pagedown':
            selected += page_size

def _choose_language_numbered(title, available, default=None):
    """Fallback para pipes, testes e terminais sem leitura de tecla no Windows."""
    print('\n  ' + title)
    for index, (code, name) in enumerate(available, 1):
        marker = ' (atual)' if default == code else ''
        print('    [{:>2}] {} ({}){}'.format(index, name, code, marker))
    print('    [ 0] Voltar')
    default_idx = next((index for index, item in enumerate(available, 1)
                        if item[0] == default), 0)
    while True:
        raw = _prompt('  Escolha (ENTER={:02d}): '.format(default_idx), str(default_idx))
        if raw == '0':
            return None
        try:
            value = int(raw) if raw else default_idx
            if 1 <= value <= len(available):
                return _argos_code(available[value - 1][0])
        except (ValueError, IndexError):
            pass
        print('  Invalido.')

def choose_language(title, available, default=None):
    if os.name == 'nt' and sys.stdin.isatty():
        return _choose_language_grid(title, available, default)
    return _choose_language_numbered(title, available, default)

def configure_languages(source_code=None, target_code=None, flow_mode='direct', intermediate_language=None):
    scripted = bool(source_code or target_code)
    cfg = load_config()
    src_default = _argos_code(cfg.get('source_language', 'en'))
    tgt_default = _argos_code(cfg.get('target_language', 'pt-BR'))
    print('\n' + '=' * 60)
    print('  Configuracao de idiomas')
    print('=' * 60)
    try:
        available = available_models(refresh=True)
    except Exception:
        available = {}
    if not available:
        print('\n[ERRO] Nao foi possivel carregar o catalogo Argos (sem internet?).')
        if not scripted:
            _prompt('\nENTER para voltar...')
        return False
    names = _language_names(available)
    sources = sorted({s for s, _ in available}, key=lambda c: names.get(c, c).lower())
    if source_code:
        src = _argos_code(source_code)
        if src not in sources:
            print('[ERRO] Idioma de origem indisponivel: {}'.format(source_code))
            return False
    else:
        try:
            detected = detect_game_language(sources)
        except Exception as exc:
            _log('[idioma] deteccao automatica falhou: {}'.format(exc))
            detected = None
        src = None
        suggested = src_default
        if detected:
            suggested = detected['code']
            print('\n  Idioma original detectado: {} ({})'.format(
                names.get(suggested, suggested), _config_code(suggested)))
            print('  Confianca: {} ({:.0%})'.format(
                detected['level'], detected['confidence']))
            print('  Evidencia: {}'.format(detected['evidence']))
            answer = _prompt('\n  ENTER: confirmar   C: escolher outro   Q: voltar\n  > ', '')
            if answer.lower() in ('', 's', 'sim', 'y', 'yes'):
                src = suggested
            elif answer.lower() in ('q', '0', 'voltar'):
                return False
        if src is None:
            src = choose_language('Idioma original do jogo:',
                                  [(c, names.get(c, c)) for c in sources], default=suggested)
        if src is None:
            return False
    chained = flow_mode == 'chain'
    middle = _argos_code(intermediate_language or 'en')
    targets = sorted(
        ({t for s, t in available if s == middle and t != middle}
         if chained and (src, middle) in available else
         {t for s, t in available if s == src}),
        key=lambda c: names.get(c, c).lower())
    if not targets:
        print('\n[ERRO] Nenhum destino disponivel para {}.'.format(src))
        if not scripted:
            _prompt('\nENTER para voltar...')
        return False
    if target_code:
        tgt = _argos_code(target_code)
        if tgt not in targets:
            print('[ERRO] Fluxo indisponivel: {}{} -> {}'.format(src, ' -> ' + middle if chained else '', target_code))
            return False
    else:
        tgt = choose_language('Traduzir para:',
                              [(c, names.get(c, c)) for c in targets], default=tgt_default)
        if tgt is None:
            return False
    pairs = [(src, middle), (middle, tgt)] if chained else [(src, tgt)]
    print('\n  Fluxo: {}'.format(' -> '.join([source for source, _ in pairs] + [pairs[-1][1]])))
    for pair_source, pair_target in pairs:
        if (pair_source, pair_target) not in installed_models():
            ans = ('s' if scripted else _prompt('\nModelo {} -> {} nao instalado. Baixar agora? [S/n]: '.format(pair_source, pair_target), 's'))
            if ans.lower() not in ('s', '', 'y', 'sim', 'yes') or not install_pair(pair_source, pair_target):
                print('[ERRO] O modelo nao foi instalado; a configuracao anterior foi mantida.')
                if not scripted: _prompt('\nENTER para voltar...')
                return False
        if not validate_pair(pair_source, pair_target):
            print('[ERRO] O par {} -> {} nao ficou operacional.'.format(pair_source, pair_target))
            if not scripted: _prompt('\nENTER para voltar...')
            return False
    cfg['source_language'] = _config_code(src)
    cfg['target_language'] = _config_code(tgt)
    cfg['flow_mode'] = 'chain' if chained else 'direct'
    cfg['intermediate_language'] = _config_code(middle) if chained else None
    cfg['languages_configured'] = True
    save_config(cfg)
    patch_autotranslator_ini(src, tgt)
    if not scripted:
        _prompt('\nENTER para voltar...')
    return True

def show_installed_models():
    im = installed_models()
    print('\nMODELOS INSTALADOS')
    print('-' * 60)
    if not im:
        print('Nenhum modelo instalado.')
    for (s, t), info in sorted(im.items()):
        print('  {} -> {}  v{}'.format(info['from'], info['to'], info['version']))
    print('\n  Uso de disco: {} ({})'.format(_fmt_size(cache_size()), cache_path()))
    _prompt('\nENTER para voltar...')

def _do_install_wizard(pause=True):
    print('\n' + '=' * 60)
    print('  Instalacao: BepInEx + XUnity AutoTranslator')
    print('=' * 60)
    info = detect_game()
    if not info['valid']:
        print('[ERRO] Esta pasta nao foi reconhecida como jogo Unity: {}'.format(GAME_DIR))
        _prompt('\nENTER para voltar...')
        return False
    rt = info['runtime']
    arch = info['architecture']
    if rt == 'Unknown' or arch not in ('x86', 'x64'):
        print('[ERRO] Nao foi possivel determinar runtime/arquitetura com seguranca.')
        show_diagnostics(wait=False)
        _prompt('\nENTER para voltar...')
        return False
    print('  Runtime: {} {} (confianca {})'.format(rt, arch, info['confidence']))
    def on_step(n, msg):
        print('  passo {}: {}'.format(n, msg))
    try:
        if not install_bepinex_xunity(runtime=rt, architecture=arch, on_step=on_step):
            print('[ERRO] Falha na instalacao.')
            _prompt('\nENTER para voltar...')
            return False
    except Exception as e:
        print('[ERRO] {}'.format(e))
        _prompt('\nENTER para voltar...')
        return False
    print('[OK] Instalacao concluida. Configure idiomas antes de iniciar.')
    if pause:
        _prompt('\nENTER para voltar...')
    return True

def show_diagnostics(wait=True):
    info = detect_game()
    status = installation_status(info)
    print('\nDIAGNOSTICO UAT-UNITY')
    print('-' * 60)
    print('  Pasta do UAT:       {}'.format(UAT_DIR))
    print('  Pasta do jogo:      {}'.format(GAME_DIR))
    if MODELS_DIR != PORTABLE_MODELS_DIR:
        print('  Modelos (alias):    {}'.format(MODELS_DIR))
    print('  Jogo Unity valido:  {}'.format('sim' if info['valid'] else 'NAO'))
    print('  Executavel:         {}'.format(info['exe'] or 'nao encontrado'))
    print('  Data:               {}'.format(info['data_dir'] or 'nao encontrada'))
    print('  Unity:              {}'.format(info['unity_version'] or 'desconhecida'))
    print('  Runtime:            {} (confianca {})'.format(info['runtime'], info['confidence']))
    print('  Arquitetura:        {}'.format(info['architecture']))
    print('  Sinais:             {}'.format(', '.join(
        key for key, value in info['signals'].items() if value) or 'nenhum'))
    print('  BepInEx:            {}'.format(status['bepinex_runtime'] or 'nao instalado'))
    print('  XUnity:             {}'.format('instalado' if status['xunity'] else 'nao instalado'))
    print('  Compatibilidade:    {}'.format('OK' if status['runtime_match'] else 'CONFLITO'))
    if wait:
        _prompt('\nENTER para voltar...')
    return info

def _do_start():
    cfg = load_config()
    src = _argos_code(cfg.get('source_language', 'en'))
    tgt = _argos_code(cfg.get('target_language', 'pt-BR'))
    if (src, tgt) not in installed_models():
        print('\n[ERRO] Modelo {} -> {} nao instalado. Instale via [C].'.format(src, tgt))
        _prompt('\nENTER para voltar ao menu...')
        return
    exe = find_game_exe()
    if not exe:
        print('\n[ERRO] .exe do jogo nao encontrado em: {}'.format(GAME_DIR))
        _prompt('\nENTER para volar ao menu...')
        return
    print('\n  Subindo servidor UAT...', flush=True)
    patch_autotranslator_ini(cfg.get('source_language', 'en'), cfg.get('target_language', 'pt-BR'))
    start_server()
    waited = 0
    while not server_ready() and waited < 30:
        time.sleep(1)
        waited += 1
    if not server_ready():
        print('[ERRO] Server nao respondeu. Veja Logs/uat_server.log')
        _prompt('\nENTER para volar ao menu...')
        return
    print('[OK] Server online. Abrindo jogo: {}'.format(os.path.basename(exe)))
    try:
        proc = subprocess.Popen([exe], cwd=GAME_DIR)
        proc.wait()
    except Exception as e:
        print('[ERRO] abrir jogo: {}'.format(e))
        _prompt('\nENTER para volar ao menu...')
        return
    print('[OK] Jogo fechado. Parando servidor...')
    stop_server()
    _prompt('\nENTER para volar ao menu...')

def menu():
    cfg = load_config()
    src = _argos_code(cfg.get('source_language', 'en'))
    tgt = _argos_code(cfg.get('target_language', 'pt-BR'))
    has = (src, tgt) in installed_models()
    print('\n' + '=' * 60)
    print('  UAT-Unity - Universal Auto Translator for Unity')
    print('=' * 60)
    print('  Jogo: {}  ({})'.format(game_name(), GAME_DIR))
    info = detect_game()
    rt = info['runtime']
    print('  Runtime: {} {}  | Unity: {}'.format(
        rt, info['architecture'], info['unity_version'] or 'desconhecida'))
    print('  Configuracao atual: {} -> {}'.format(_config_code(src), _config_code(tgt)))
    print('  Modelo: {}'.format('instalado e pronto' if has else 'NAO INSTALADO'))
    print('  Servidor: {}'.format('online' if server_ready() else 'offline'))
    print('  Uso de disco modelos: {}'.format(_fmt_size(cache_size())))
    if is_first_run():
        print('\n  [AVISO] BepInEx/XUnity nao encontrados. Rode [I] para instalar.')
    print('\n  [ENTER] Iniciar tradutor e abrir o jogo')
    print('  [C]     Configurar idiomas / baixar modelo')
    print('  [I]     Instalar BepInEx + XUnity (GitHub)')
    print('  [R]     Reparar/validar instalacao')
    print('  [M]     Ver modelos instalados')
    print('  [D]     Diagnostico do jogo')
    print('  [S]     Subir/parar servidor')
    print('  [Q]     Sair')
    return _prompt('\n  > ').strip().lower()

def main():
    args = sys.argv[1:]
    command = args[0].lower() if args else ''
    if command in ('__server__', 'server'):
        _run_server_forever()
        return
    if command in ('__diagnose__', 'diagnose', 'diagnostico'):
        show_diagnostics(wait=False)
        return
    if command in ('__install__', 'install', 'instalar', 'repair', 'reparar'):
        rt = args[1] if len(args) > 1 else None
        arch = args[2] if len(args) > 2 else None
        install_bepinex_xunity(runtime=rt, architecture=arch)
        return
    if command in ('config', 'configure', 'idiomas', 'languages'):
        if not detect_game()['valid']:
            print('[ERRO] Configuracao recusada: jogo Unity nao encontrado em {}'.format(GAME_DIR))
            return
        source = args[1] if len(args) > 1 else None
        target = args[2] if len(args) > 2 else None
        flow_mode = args[3] if len(args) > 3 else 'direct'
        intermediate = args[4] if len(args) > 4 else None
        configure_languages(source, target, flow_mode, intermediate)
        return
    if command in ('models', 'modelos'):
        show_installed_models()
        return
    info = detect_game()
    if not info['valid']:
        print('\n[ERRO] O UAT nao encontrou um jogo Unity valido.')
        show_diagnostics(wait=False)
        print('\nCopie a pasta uat-unity para dentro da raiz do jogo, ou copie o pack')
        print('inteiro na raiz. Para desenvolvimento, defina UAT_GAME_DIR.')
        _prompt('\nENTER para sair...')
        return
    # Primeira vez (sem BepInEx): assistente automatico
    if is_first_run():
        print('\n' + '=' * 60)
        print('  Primeira execucao - assistente de instalacao')
        print('=' * 60)
        if _do_install_wizard(pause=False):
            print('\n  Agora escolha os idiomas (modelo sera baixado):')
            configure_languages()
    elif not load_config().get('languages_configured', False):
        print('\n  Instalacao encontrada. Confirme agora os idiomas do jogo:')
        configure_languages()
    while True:
        choice = menu()
        if choice == '':
            _do_start()
        elif choice == 'c':
            configure_languages()
        elif choice == 'i':
            _do_install_wizard()
        elif choice == 'r':
            _do_install_wizard()
        elif choice == 'm':
            show_installed_models()
        elif choice == 'd':
            show_diagnostics()
        elif choice == 's':
            if server_ready():
                stop_server()
                print('Servidor parado.')
            else:
                start_server()
                w = 0
                while not server_ready() and w < 15:
                    time.sleep(1)
                    w += 1
                print('Server online' if server_ready() else 'Server nao respondeu')
            _prompt('\nENTER para volar ao menu...')
        elif choice in ('q', 'esc'):
            stop_server()
            print('Saiu.')
            return
        else:
            print('Invalido.')

if __name__ == '__main__':
    main()
