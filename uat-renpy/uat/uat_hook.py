import sys
import os
import json
import re
import time
import threading
import ssl
import urllib.request
import urllib.parse
import urllib.error
import weakref

UAT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(UAT_DIR, "uat_config.json")
CACHE_PATH = os.path.join(UAT_DIR, "uat_cache.json")
WORDS_PATH = os.path.join(UAT_DIR, "uat_words.json")
LOG_PATH = os.path.join(UAT_DIR, "UAlogs", "uat_log.txt")
SESSION_PATH = os.path.join(UAT_DIR, "uat_session.active")

def _touch_session():
    try:
        with open(SESSION_PATH, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:
        pass

def _clear_session():
    try:
        if os.path.exists(SESSION_PATH):
            os.remove(SESSION_PATH)
    except Exception:
        pass

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {}

_cache_name = CONFIG.get("cache_file", "uat_cache.json")
_words_name = CONFIG.get("words_file", "uat_words.json")
CACHE_PATH = _cache_name if os.path.isabs(_cache_name) else os.path.join(UAT_DIR, _cache_name)
WORDS_PATH = _words_name if os.path.isabs(_words_name) else os.path.join(UAT_DIR, _words_name)

PROVIDER = CONFIG.get("provider", "google_free")
SOURCE = CONFIG.get("source_language", "en")
TARGET = CONFIG.get("target_language", "ptbr")
MAX_LEN = CONFIG.get("max_text_length", 500)
SHOW_CONSOLE = CONFIG.get("show_console", True)

sys.path.insert(0, UAT_DIR)
import uat_log
uat_log.UATLogger.init(log_path=LOG_PATH, show_console=SHOW_CONSOLE)
log = uat_log.UATLogger

try:
    import uat_lt
except Exception:
    uat_lt = None

_cache = {}
_words = {}
_cache_lock = threading.Lock()
_cache_dirty = False
_cache_save_lock = threading.Lock()
_cache_save_timer = None
CACHE_SAVE_DELAY = float(CONFIG.get("cache_save_delay", 2.0))

def _load_json(path):
    """Carrega JSON tolerante a BOM e a erros (arquivos editados por usuarios)."""
    if not os.path.exists(path):
        return None
    for enc in ("utf-8", "utf-8-sig"):
        try:
            with open(path, "r", encoding=enc) as f:
                return json.load(f)
        except (ValueError, UnicodeDecodeError):
            continue
    return None

def _load_cache():
    global _cache, _words
    data = _load_json(CACHE_PATH)
    if data is not None:
        _cache = data if isinstance(data, dict) else {}
        log.info(f"Cache carregado: {len(_cache)} frases")
    try:
        wdata = _load_json(WORDS_PATH)
        if wdata is not None:
            _words = wdata if isinstance(wdata, dict) else {}
            log.info(f"Palavras carregadas: {len(_words)}")
    except Exception:
        _words = {}

def _save_cache():
    global _cache_dirty, _cache_save_timer
    with _cache_save_lock:
        _cache_save_timer = None
    with _cache_lock:
        if not _cache_dirty:
            return
        cache_snapshot = dict(_cache)
        words_snapshot = dict(_words)
        _cache_dirty = False
    for path in (CACHE_PATH, WORDS_PATH):
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent)
            except OSError:
                pass
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_snapshot, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
    except Exception as e:
        log.error(f"Falha salvar cache: {e}")
        with _cache_lock:
            _cache_dirty = True
    try:
        with open(WORDS_PATH, "w", encoding="utf-8") as f:
            json.dump(words_snapshot, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
    except Exception as e:
        log.error(f"Falha salvar palavras: {e}")

def _mark_cache_dirty():
    """Agrupa gravacoes para nao serializar todo o cache em cada fala."""
    global _cache_dirty, _cache_save_timer
    with _cache_lock:
        _cache_dirty = True
    with _cache_save_lock:
        if _cache_save_timer is None:
            _cache_save_timer = threading.Timer(CACHE_SAVE_DELAY, _save_cache)
            _cache_save_timer.daemon = True
            _cache_save_timer.start()

_load_cache()

import atexit
atexit.register(_save_cache)
atexit.register(_clear_session)

# --- Ren'Py variable/tag protection ---

_RENPY_PATTERN = re.compile(r'(\[[^\]]*\]|\{[^}]*\})')

def _protect_renpy(text):
    """Protege [variaveis] e {tags} do Ren'Py contra traducao.
    Usa placeholder @@N@@ que sobrevive a traducores (sem chars nulos)."""
    tokens = {}
    def _replacer(m):
        tok = f"@@{len(tokens)}@@"
        tokens[tok] = m.group(1)
        return tok
    protected = _RENPY_PATTERN.sub(_replacer, text)
    return _protect_emojis(protected, tokens), tokens

def _next_codepoint(text, index):
    """Le um codepoint inclusive em builds Python 2 com Unicode estreito."""
    first = ord(text[index])
    if 0xD800 <= first <= 0xDBFF and index + 1 < len(text):
        second = ord(text[index + 1])
        if 0xDC00 <= second <= 0xDFFF:
            return (0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00), index + 2)
    return first, index + 1

def _emoji_codepoint(cp):
    return (0x1F000 <= cp <= 0x1FAFF or 0x1FC00 <= cp <= 0x1FFFF
            or 0x2600 <= cp <= 0x27BF or 0x2300 <= cp <= 0x23FF)

def _protect_emojis(text, tokens):
    """Transforma emojis, sequencias ZWJ e keycaps em tokens restauraveis."""
    out = []
    i = 0
    while i < len(text):
        cp, end = _next_codepoint(text, i)
        is_keycap = cp in (0x23, 0x2A) or 0x30 <= cp <= 0x39
        j = end
        if is_keycap:
            if j < len(text):
                cp2, j2 = _next_codepoint(text, j)
                if cp2 == 0xFE0F:
                    j = j2
            if j < len(text):
                cp2, j2 = _next_codepoint(text, j)
                if cp2 == 0x20E3:
                    end = j2
                else:
                    is_keycap = False
            else:
                is_keycap = False
        if _emoji_codepoint(cp) or is_keycap:
            j = end
            while j < len(text):
                cp2, j2 = _next_codepoint(text, j)
                if (cp2 in (0xFE0E, 0xFE0F, 0x200D, 0x20E3)
                        or 0x1F3FB <= cp2 <= 0x1F3FF or _emoji_codepoint(cp2)):
                    j = j2
                    continue
                break
            tok = "@@{}@@".format(len(tokens))
            tokens[tok] = text[i:j]
            out.append(tok)
            i = j
        else:
            out.append(text[i:end])
            i = end
    return "".join(out)

def _restore_renpy(text, tokens):
    """Restaura [variaveis] e {tags} apos traducao.
    Tenta tokens @@N@@ e tambem \x00_N_\x00 por compatibilidade."""
    for tok, orig in tokens.items():
        if tok in text:
            # Argos pode devolver "@@1@@@@"; consome arrobas extras junto do token.
            text = re.sub(re.escape(tok) + r'@+', lambda _m: orig, text)
            text = text.replace(tok, orig)
        else:
            alt = tok.replace("@@", "\x00").replace("_", "")
            if alt in text:
                text = text.replace(alt, orig)
    return _sanitize_renpy_tags(text)

_TAG_FIX = re.compile(r'(\{[^{}]*\})')
def _sanitize_renpy_tags(text):
    """Remove espacos invalidos dentro de tags Ren'Py, ex: {color=#e93a7c } -> {color=#e93a7c}."""
    def _fix(m):
        inner = m.group(1)
        return inner.replace(" ", "")
    return _TAG_FIX.sub(_fix, text)

# Textos com tags de estilo Ren'Py ({...} ou [...]) NAO sao traduzidos pelos
# hooks de UI (menus/botoes) para evitar que a API corrompa as tags e quebre
# o render (ex: Color string '#e93a7c '). O dialogo (do_display) ainda traduz.
_STYLE_TAG = re.compile(r'[\{\[]')
def _has_style_tag(text):
    return bool(_STYLE_TAG.search(text))

# --- Cache de palavras: reaproveita traducoes parciais sem bater na API ---

import re as _re
_WORD_SPLIT = _re.compile(r"[A-Za-z']+")
_STOP = set("a an the and or but of to in on at for with he she it his her my your we you they i is am are was were be been do does did has have had not no s t re ll d m o".split())

def _extract_words(en_text, pt_text):
    """Tenta mapear palavras EN->PT por posicao/quantidade (heuristica simples)."""
    en_words = [w for w in _WORD_SPLIT.findall(en_text.lower()) if w not in _STOP and len(w) > 2]
    pt_words = [w for w in _WORD_SPLIT.findall(pt_text.lower()) if len(w) > 2]
    if len(en_words) == len(pt_words) and 0 < len(en_words) <= 12:
        for e, p in zip(en_words, pt_words):
            if e not in _words:
                _words[e] = p

def _apply_known_words(text):
    """Pre-substitui palavras ja conhecidas antes de chamar a API."""
    if not _words:
        return text
    def _r(m):
        w = m.group(0).lower()
        return _words.get(w, m.group(0))
    return _WORD_SPLIT.sub(_r, text)

# --- API ---

# --- Google Translate V1 (free scraping) ---

def _translate_google_v1(texts):
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&dt=t&sl=" + SOURCE + "&tl=" + TARGET
    data = urllib.parse.urlencode({"q": "\n".join(texts)}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded"
    })
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    sentences = result[0]
    out = []
    cur = ""
    i = 0
    for s in sentences:
        if s[0] is None:
            continue
        cur += s[0]
        if i < len(texts) - 1 and cur.endswith(texts[i][-1:] if texts[i] else ""):
            out.append(cur)
            cur = ""
            i += 1
    if cur:
        out.append(cur)
    while len(out) < len(texts):
        out.append(texts[len(out)])
    return out

# --- Google Translate V2 (batchexecute, mais resiliente) ---

_google_v2_rpcs = 0

def _translate_google_v2(texts):
    global _google_v2_rpcs
    _google_v2_rpcs += 1
    rpcid = "MkEWBc"
    rpcs = []
    for t in texts:
        inner = json.dumps([[t, SOURCE, TARGET, True], [None]], ensure_ascii=False)
        rpcs.append([rpcid, inner, None, "generic"])
    payload = json.dumps([rpcs], ensure_ascii=False)
    body = "f.req=" + urllib.parse.quote(payload)
    req = urllib.request.Request(
        "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute",
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "User-Agent": "Mozilla/5.0",
        }
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        raw = resp.read().decode("utf-8")
    out = []
    raw = raw.replace(")]}'\n", "").replace(")]}'", "").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list) and len(data) > 0:
            items = data[0] if isinstance(data[0], list) else data
            for item in items:
                if isinstance(item, list) and len(item) >= 2:
                    resp_str = item[1]
                    if resp_str and isinstance(resp_str, str):
                        try:
                            resp_data = json.loads(resp_str)
                            trans = resp_data[0][0]
                            out.append(trans)
                        except Exception:
                            pass
    except json.JSONDecodeError as e:
        log.error(f"V2 JSON error: {e}")
        log.hook(f"V2 raw[:300]: {repr(raw[:300])}")
    while len(out) < len(texts):
        out.append(texts[len(out)])
    return out

# --- DeepL Free (web API) ---

_deepl_id = 1

def _translate_deepl_free(texts):
    global _deepl_id
    dl = TARGET.upper()[:2]
    sl = SOURCE.upper()[:2]
    _deepl_id += len(texts)
    jobs = []
    for t in texts:
        jobs.append({
            "kind": "default", "raw_en_sentence": t,
            "raw_en_context_before": [], "raw_en_context_after": [],
            "preferred_num_beams": 4
        })
    body = json.dumps({
        "jsonrpc": "2.0", "method": "LMT_handle_jobs",
        "params": {
            "jobs": jobs,
            "lang": {
                "user_preferred_langs": [sl, dl],
                "source_lang_computed": sl, "target_lang": dl
            },
            "priority": -1, "commonJobParams": {}
        },
        "id": _deepl_id
    }, separators=(",", ":"))
    req = urllib.request.Request(
        "https://www2.deepl.com/jsonrpc",
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "*/*", "User-Agent": "DeepL/2.11.11",
        }
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    beams = result.get("result", {}).get("translations", [])
    out = []
    for b in beams:
        sentences = b.get("beams", [])
        if sentences:
            out.append(sentences[0].get("postprocessed_sentence", ""))
        else:
            out.append("")
    while len(out) < len(texts):
        out.append(texts[len(out)])
    return out

def _translate_local(texts):
    """API local (LibreTranslate / Bergamot). REST padrao:
    POST {endpoint}  body: {"q":[...], "source":sl, "target":dl, "format":"text"}
    Retorna lista de textos traduzidos."""
    # Se o servidor embutido ainda nao subiu, nao bloqueia: retorna original.
    if uat_lt is not None and not uat_lt.is_ready():
        return list(texts)
    cfg = CONFIG.get("local", {})
    endpoint = cfg.get("endpoint") or "http://localhost:5000/translate"
    api_key = cfg.get("api_key", "")
    timeout = float(cfg.get("timeout", 5))
    sl = SOURCE
    dl = TARGET
    payload = {
        "q": list(texts),
        "source": sl,
        "target": dl,
        "format": "text",
    }
    if api_key:
        payload["api_key"] = api_key
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    # LibreTranslate retorna {"translatedText": ["..."]} (dict com lista)
    # ou [{"translatedText": "..."}] (lista de dicts)
    raw = None
    if isinstance(result, list):
        raw = [r.get("translatedText", "") if isinstance(r, dict) else r for r in result]
    elif isinstance(result, dict):
        raw = result.get("translatedText", "")
    if isinstance(raw, list):
        out = [str(x) for x in raw]
    else:
        out = [str(raw)]
    while len(out) < len(texts):
        out.append(texts[len(out)])
    return out


# --- Provider registry com fallback ---

_PROVIDER_MAP = {
    "local": _translate_local,
    "google_free": _translate_google_v1,
    "google": _translate_google_v1,
    "google_v2": _translate_google_v2,
    "deepl_free": _translate_deepl_free,
    "deepl": _translate_deepl_free,
}

def translate_batch(texts, retries=2):
    """Tenta todos os tradutores em ordem, com retry."""
    log.hook(f"[BATCH_DEBUG] chamado com {len(texts)} textos, PROVIDER={PROVIDER}")
    if not texts:
        return []
    order = []
    if PROVIDER == "local":
        # Apenas API local (sem fallback pros outros tradutores)
        func = _PROVIDER_MAP.get("local")
        if func:
            order.append(("local", func))
    else:
        for name in [PROVIDER, "google_free", "google_v2", "deepl_free", "deepl"]:
            func = _PROVIDER_MAP.get(name)
            if func and (name, func) not in order:
                order.append((name, func))
    log.hook(f"[BATCH] Ordem: {' -> '.join(n for n, _ in order)}")
    for retry in range(retries + 1):
        if retry > 0:
            time.sleep(1.5)
            log.warn(f"Retry {retry}/{retries}...")
        for pname, pfunc in order:
            try:
                result = pfunc(texts)
                diff = sum(1 for t, r in zip(texts, result) if r and r != t)
                log.api(f"{pname}: {diff}/{len(texts)} traduzidos")
                for t, r in zip(texts, result):
                    if r and r != t:
                        log.ok(f"TRAD: {repr(t[:80])} -> {repr(r[:80])}")
                    elif r == t and len(t) > 3:
                        log.hook(f"IDENT {pname}: {repr(t[:60])}")
                        if pname == "google_free":
                            log.hook(f"[V1 ECHO] enviado={repr(t[:80])} recebido={repr(r[:80])}")
                # Se o primeiro provider traduziu algo, usa. Senao tenta o proximo.
                if diff > 0:
                    return result
                if PROVIDER == "local":
                    # Local sem diff: servidor ainda nao pronto ou sem mudanca.
                    # Sem retry (evita o sleep de 1.5s por linha).
                    return result
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    log.warn(f">>> RATE LIMIT: {pname}, tentando alternativo...")
                else:
                    log.error(f"Erro HTTP {e.code} em {pname}")
            except Exception as e:
                log.error(f"Erro {pname}: {e}")
    log.error(">>> TODOS OS TRADUTORES FALHARAM")
    return list(texts)

# --- Worker continuo com delay entre chamadas ---

_translate_queue = []
_queue_lock = threading.Lock()
_queue_ready = threading.Condition(_queue_lock)
_worker_thread_started = False
_translating = set()
LOCAL_BATCH_SIZE = max(1, int(CONFIG.get("local_batch_size", 8)))
UI_REFRESH_DELAY = max(0.02, float(CONFIG.get("ui_refresh_delay", 0.10)))
_ui_refresh_lock = threading.Lock()
_ui_refresh_timer = None
_ui_waiters_lock = threading.Lock()
_ui_waiters = {}
_ui_refresh_requested = False
_periodic_refresh_installed = False

def _remember_ui_widget(text, widget):
    """Guarda widgets vivos para troca direta quando a traducao chegar."""
    try:
        ref = weakref.ref(widget)
    except Exception:
        return
    with _ui_waiters_lock:
        refs = _ui_waiters.setdefault(text, [])
        if not any(r() is widget for r in refs):
            refs.append(ref)
        if len(refs) > 32:
            del refs[:-32]

def _apply_waiting_ui_widgets():
    ready = []
    with _ui_waiters_lock:
        for original, refs in list(_ui_waiters.items()):
            with _cache_lock:
                translated = _cache.get(original)
            if translated and translated != original:
                ready.append((translated, refs))
                del _ui_waiters[original]
    for translated, refs in ready:
        for ref in refs:
            widget = ref()
            if widget is None:
                continue
            try:
                widget.set_text(translated, substitute=False, update=True)
            except TypeError:
                try:
                    widget.set_text(translated)
                except Exception:
                    pass
            except Exception:
                pass

def _periodic_ui_refresh():
    """Executado pelo Ren'Py na thread principal (~20 Hz)."""
    global _ui_refresh_requested
    with _ui_refresh_lock:
        if not _ui_refresh_requested:
            return
        _ui_refresh_requested = False
    _apply_waiting_ui_widgets()
    _perform_ui_refresh()

def _worker_loop():
    """Worker continuo: traduz 1 por vez (MaxConcurrency=1), 0.9s entre
    requests (XUnity DefaultTranslationDelay), e edita a caixa so se o
    dialogo atual ainda estiver na tela."""
    log.hook("[WORKER] thread iniciada")
    while True:
        with _queue_ready:
            while not _translate_queue:
                _queue_ready.wait()
            batch_size = LOCAL_BATCH_SIZE if PROVIDER == "local" else 1
            batch = _translate_queue[:batch_size]
            del _translate_queue[:batch_size]
        # Se o servidor local embutido ainda nao subiu, devolve pra fila e espera.
        if PROVIDER == "local" and uat_lt is not None and not uat_lt.is_ready():
            if time.time() < uat_lt.deadline():
                with _queue_ready:
                    _translate_queue[:0] = batch
                    _queue_ready.notify()
                time.sleep(1.0)
                continue
        log.hook(f"[WORKER] pegou {len(batch)} da fila")
        n = len(batch)
        log.hook(f"[WORKER] Traduzindo lote de {n} texto(s)...")
        originals = [b[0] for b in batch]   # texto cru
        protected_list = [b[1] for b in batch]  # texto protegido
        translated = [None] * n
        try:
            results = translate_batch(protected_list)
        except Exception as e:
            log.error(f"[WORKER] lote erro: {e}")
            results = protected_list
        for i, (orig, prot, tokens) in enumerate(batch):
            try:
                trans = results[i] if i < len(results) else prot
                if isinstance(trans, list):
                    trans = trans[0] if trans else prot
                if not isinstance(trans, str):
                    trans = str(trans)
                trans = _restore_renpy(trans, tokens)
                _extract_words(orig, trans)
                translated[i] = trans
                log.hook(f"[WORKER] item {i}: res={repr(trans[:60])}")
            except Exception as e:
                log.error(f"[WORKER] item {i} erro: {e}")
                translated[i] = prot
        try:
            with _cache_lock:
                for orig, prot, trans in zip(originals, protected_list, translated):
                    if not trans or trans == prot or trans == orig:
                        _translating.discard(prot)
                        continue
                    _cache[orig] = trans
                    _cache[prot] = trans
                    _cache[trans] = trans
                    _translating.discard(prot)
            _mark_cache_dirty()
            acertos = sum(1 for o, t in zip(originals, translated) if t and t != o)
            log.hook(f"[WORKER] Lote concluido: {acertos}/{n} traduzidos")
            if acertos:
                _request_ui_refresh()
            # Edita a caixa so se o dialogo atual foi o traduzido E ainda tiver na tela
            if acertos:
                with _dialogue_lock:
                    cur = _current_dialogue.get("what")
                if cur in originals and cur in _cache and _cache[cur] != cur:
                    _request_dialogue_refresh()
        except Exception as e:
            log.error(f"Worker erro: {e}")
            with _queue_lock:
                for b in batch:
                    _translating.discard(b[1])

# --- Logger helper ---

_logged_hooks = set()

def log_once(tag, msg):
    if tag not in _logged_hooks:
        _logged_hooks.add(tag)
        log.hook(f"[{tag}] {msg}")

# --- Hooks ---

def _translate_text(text, blocking=False):
    """Traducao. Se blocking=True, chama a API direto (sincrono, timeout 2.5s).
    Se non-blocking, enfileira no worker. Retorna original se falhar."""
    if not isinstance(text, str) or not text.strip():
        return text
    try:
        with _cache_lock:
            cached_value = _cache.get(text)
        if cached_value is not None:
            _unused, expected_tokens = _protect_renpy(text)
            if all(value in cached_value for value in expected_tokens.values()):
                return cached_value
            with _cache_lock:
                _cache.pop(text, None)
            log.warn("Cache antigo sem tags/emoji foi descartado")
        protected, tokens = _protect_renpy(text)
        if blocking:
            # Traducao sincrona direto na API (o que vai pra tela)
            try:
                res = translate_batch([protected])
                translated = res[0] if res else protected
                if translated and translated != protected:
                    translated = _restore_renpy(translated, tokens)
                    with _cache_lock:
                        _cache[text] = translated
                        _cache[protected] = translated
                        _cache[translated] = translated
                    _mark_cache_dirty()
                    return translated
            except Exception as e:
                log.warn(f"Block traduccao falhou: {e}")
            return text
        # Non-blocking: enfileira no worker
        with _queue_ready:
            if protected not in _translating:
                _translating.add(protected)
                _translate_queue.append((text, protected, tokens))
                _queue_ready.notify()
    except Exception:
        pass
    return text

_current_dialogue = {"what": None, "who": None}
_dialogue_lock = threading.Lock()

def _refresh_current_dialogue():
    """Se o dialogo ATUAL ja foi traduzido, edita o widget Text da
    screen 'say' com PT (XUnity-style: edita a caixa ja visivel)."""
    with _dialogue_lock:
        cur = _current_dialogue.get("what")
        who = _current_dialogue.get("who")
    if not cur:
        return
    with _cache_lock:
        translated = _cache.get(cur)
    if not translated or translated == cur:
        return
    try:
        import renpy
        scr = renpy.display.screen.get_screen("say")
        if scr is None:
            return

        # Acha o widget Text dentro da screen say e re-escreve direto.
        target = None

        def _find_text(node):
            if node is None:
                return None
            if (hasattr(node, "set_text") and hasattr(node, "text_parameter")
                    and getattr(node, "text_parameter", None)):
                return node
            children = []
            for attr in ("child_list", "children", "child"):
                v = getattr(node, attr, None)
                if v:
                    if isinstance(v, (list, tuple)):
                        children.extend(v)
                    else:
                        children.append(v)
            for ch in children:
                r = _find_text(ch)
                if r is not None:
                    return r
            return None

        try:
            target = _find_text(scr)
        except Exception:
            target = None
        if target is not None:
            try:
                target.set_text(translated, substitute=False, update=True)
                log.ok(f"TRADUZ (apos aparecer): {repr(translated[:80])}")
                return
            except Exception as e:
                log.warn(f"set_text no widget falhou: {e}")
        # Fallback: re-show da screen (pode nao re-render no Ren'Py 8)
        try:
            renpy.display.screen.show_screen("say", who=who, what=translated, _layer="screens")
            renpy.restart_interaction()
            log.ok(f"TRADUZ (apos aparecer, fallback): {repr(translated[:80])}")
        except Exception as e:
            log.warn(f"Falha re-render dialogo: {e}")
    except Exception as e:
        log.warn(f"Falha re-render dialogo: {e}")

def _request_dialogue_refresh():
    """Agenda mudanca visual na thread principal quando o Ren'Py oferece isso."""
    try:
        import renpy
        invoke = getattr(renpy, "invoke_in_main_thread", None)
        if invoke is not None:
            invoke(_refresh_current_dialogue)
            return
    except Exception:
        pass
    _refresh_current_dialogue()

def _perform_ui_refresh():
    """Reconstrói a interação para menus já visíveis relerem o cache."""
    try:
        _apply_waiting_ui_widgets()
        import renpy
        renpy.restart_interaction()
        log.hook("[UI] interação atualizada após tradução")
    except Exception as e:
        log.warn(f"Falha atualizar UI traduzida: {e}")

def _dispatch_ui_refresh():
    global _ui_refresh_timer
    with _ui_refresh_lock:
        _ui_refresh_timer = None
    try:
        import renpy
        invoke = getattr(renpy, "invoke_in_main_thread", None)
        if invoke is not None:
            invoke(_perform_ui_refresh)
            return
    except Exception:
        pass
    _perform_ui_refresh()

def _request_ui_refresh():
    """Agrupa conclusões próximas em um único restart_interaction."""
    global _ui_refresh_timer, _ui_refresh_requested
    with _ui_refresh_lock:
        _ui_refresh_requested = True
        if _periodic_refresh_installed:
            return
    with _ui_refresh_lock:
        if _ui_refresh_timer is not None:
            return
        _ui_refresh_timer = threading.Timer(UI_REFRESH_DELAY, _dispatch_ui_refresh)
        _ui_refresh_timer.daemon = True
        _ui_refresh_timer.start()

# --- Patch registry for save/load safety ---
# Cada hook substitui uma funcao do Ren'Py por uma funcao NOSSA (local).
# Ren'Py checa IDENTIDADE no pickle do save ("not the same object as X"),
# entao nem qualname basta. A solucao: em volta de renpy.save/renpy.load,
# restauramos os originais antes do pickle e reaplicamos os patches depois.
_PATCH_TABLE = []
def _record_patch(obj, attr, patched, original):
    _PATCH_TABLE.append((obj, attr, patched, original))
def _restore_patches():
    for obj, attr, patched, original in _PATCH_TABLE:
        try:
            setattr(obj, attr, original)
        except Exception:
            pass
def _apply_patches():
    for obj, attr, patched, original in _PATCH_TABLE:
        try:
            setattr(obj, attr, patched)
        except Exception:
            pass
def _install_save_wrap():
    """Envolve renpy.save/renpy.load p/ trocar patches por originais no pickle.
    Ren'Py checa identidade no save, entao isso eh obrigatorio."""
    import renpy
    _orig_save = getattr(renpy, "save", None)
    _orig_load = getattr(renpy, "load", None)
    if _orig_save is None or _orig_load is None:
        return False
    def _patched_save(*args, **kwargs):
        _restore_patches()
        try:
            return _orig_save(*args, **kwargs)
        finally:
            _apply_patches()
    def _patched_load(*args, **kwargs):
        _restore_patches()
        try:
            return _orig_load(*args, **kwargs)
        finally:
            _apply_patches()
    renpy.save = _patched_save
    renpy.load = _patched_load
    log.hook("Hook OK: renpy.save/load (anti-pickle)")
    return True
def _ensure_save_wrap():
    """Tenta instalar agora; se renpy.save ainda nao existe (fase2 cedo),
    agenda via config.python_callbacks (roda apos init)."""
    try:
        if _install_save_wrap():
            return
    except Exception as e:
        log.warn(f"save-wrap adiado: {e}")
    try:
        import renpy
        def _cb():
            if _install_save_wrap():
                try:
                    renpy.config.python_callbacks.remove(_cb)
                except Exception:
                    pass
        if _cb not in renpy.config.python_callbacks:
            renpy.config.python_callbacks.append(_cb)
        log.hook("save-wrap agendado (apos init)")
    except Exception as e:
        log.warn(f"Falha agendar save-wrap: {e}")

def install_hook():
    try:
        import renpy
    except Exception as e:
        log.error(f"renpy nao disponivel: {e}")
        return

    log.info("=== Instalando hooks (Fase 2) ===")
    log.info(f"Provider: {PROVIDER} | {SOURCE} -> {TARGET}")
    log.info(f"Cache: {CACHE_PATH} ({len(_cache)} entradas)")
    log.info(f"Tradutores disponiveis: google_v1, google_v2, deepl_free")
    log.info(f"Status: {'CACHE PRONTO' if _cache else 'SEM CACHE (primeira execucao)'}")

    # say_menu_text_filter DESLIGADO: ele pre-processa TODOS os nos da cena
    # (traduz "a frente"). A traduco real acontece no do_display (exibicao).
    try:
        renpy.config.say_menu_text_filter = None
        log.hook("Hook OK: say_menu_text_filter desligado (traducao no do_display)")
    except Exception as e:
        log.warn(f"Falha desligar say_menu_text_filter: {e}")

    # 1 e 2. HOOKS DE SAY (renpy.exports.say / renpy.store.say) REMOVIDOS.
    # Eram log-only, mas renpy.store.say eh variavel do STORE e vai pro
    # pickle do save -> "Can't pickle local object". Traducao real eh no
    # do_display, entao remover nao prejudica nada.
    log.hook("Hook PULADO: renpy.exports/store.say (store -> pickle)")

    # 3. renpy.ast.Say.execute
    try:
        import renpy.ast
        original_say_execute = renpy.ast.Say.execute
        def patched_say_execute(self):
            log.hook(f"[SAY_EXECUTE] who={self.who}, what={repr(self.what)[:120]}")
            # Guarda who p/ o re-render da caixa de dialogo apos traducao
            with _dialogue_lock:
                _current_dialogue["who"] = getattr(self, "who", None)
                _current_dialogue["what"] = self.what
            return original_say_execute(self)
        renpy.ast.Say.execute = patched_say_execute
        _record_patch(renpy.ast.Say, "execute", patched_say_execute, original_say_execute)
        log.hook("Hook OK: renpy.ast.Say.execute")
    except Exception as e:
        log.warn(f"Falha hook Say.execute: {e}")

    # 4-8. Hooks do pipeline de character.
    # display_say/show_display_say REMOVIDOS: sao funcoes de modulo que
    # podem ser referenciadas direto pelo jogo (ex: skill.effect) e vao pro
    # pickle -> crash no save. Sao log-only, nao fazem traducao.
    for _name, _module, _func in [
        ("ADVCharacter.__call__", "renpy.character", "ADVCharacter.__call__"),
        ("ADVCharacter.do_display", "renpy.character", "ADVCharacter.do_display"),
        ("ADVCharacter.do_show", "renpy.character", "ADVCharacter.do_show"),
    ]:
        try:
            if _func == "ADVCharacter.__call__":
                _obj = renpy.character.ADVCharacter.__call__
            elif _func == "ADVCharacter.do_display":
                _obj = renpy.character.ADVCharacter.do_display
            elif _func == "ADVCharacter.do_show":
                _obj = renpy.character.ADVCharacter.do_show
            else:
                _obj = getattr(renpy.character, _func)
            _orig = _obj
            def _make_patched(fname, orig):
                def patched(*args, **kwargs):
                    if len(args) >= 2 and isinstance(args[1], str):
                        log.hook(f"[{fname}] what={repr(args[1])[:120]}")
                    elif 'what' in kwargs and isinstance(kwargs['what'], str):
                        log.hook(f"[{fname}] what={repr(kwargs['what'])[:120]}")
                    return orig(*args, **kwargs)
                return patched
            if _func == "ADVCharacter.__call__":
                _p = _make_patched("ADVCHAR_CALL", _orig)
                renpy.character.ADVCharacter.__call__ = _p
                _record_patch(renpy.character.ADVCharacter, "__call__", _p, _orig)
            elif _func == "ADVCharacter.do_display":
                _orig_dd = _orig
                def _patched_do_display(self, who, what, *args, **kwargs):
                    # Traducao BLOQUEANTE: ja mostra PT na hora (API local eh instantanea).
                    # Se falhar, mostra INGLES (nunca trava o jogo).
                    if isinstance(what, str) and len(what) > 3:
                        with _dialogue_lock:
                            _current_dialogue["what"] = what
                            _current_dialogue["who"] = who
                        cached = _translate_text(what, blocking=True)
                        if cached != what:
                            log.ok(f"DIALOGO: {repr(what[:80])}")
                            log.ok(f"TRADUZ: {repr(cached[:80])}")
                            what = cached
                        else:
                            if what not in _logged_hooks:
                                _logged_hooks.add(what)
                                log.hook(f"DIALOGO (original): {repr(what[:80])}")
                    return _orig_dd(self, who, what, *args, **kwargs)
                renpy.character.ADVCharacter.do_display = _patched_do_display
                _record_patch(renpy.character.ADVCharacter, "do_display", _patched_do_display, _orig_dd)
            elif _func == "ADVCharacter.do_show":
                _p = _make_patched("DO_SHOW", _orig)
                renpy.character.ADVCharacter.do_show = _p
                _record_patch(renpy.character.ADVCharacter, "do_show", _p, _orig)
            else:
                _p = _make_patched(_name.upper(), _orig)
                setattr(renpy.character, _func, _p)
                _record_patch(renpy.character, _func, _p, _orig)
            log.hook(f"Hook OK: {_func} (log-only)")
        except Exception as e:
            log.warn(f"Falha hook {_func}: {e}")

    # 9 e 10. translate_string / substitute REMOVIDOS (log-only).
    # Substituir funcoes de modulo pode interferir no pickle de alguns jogos.
    log.hook("Hook PULADO: renpy.translation.translate_string (log-only)")
    log.hook("Hook PULADO: renpy.substitutions.substitute (log-only)")

    # 11. Text displayable hooks (traduz UI e interface)
    try:
        import renpy.text.text as text_mod
        Text = text_mod.Text
        if Text:
            _orig_set_text = Text.set_text
            def _patched_set_text(self, text, scope=None, substitute=False, update=True):
                orig_text = text
                if isinstance(text, str) and len(text) > 3:
                    # Se ja eh traducao nossa (no cache como valor), nao re-enfileira
                    with _cache_lock:
                        is_trans = text in _cache and _cache[text] == text
                    if not is_trans:
                        cached = _translate_text(text, blocking=False)
                        if cached != text:
                            if text not in _logged_hooks:
                                _logged_hooks.add(text)
                                log.ok(f"UI: {repr(text[:60])} -> {repr(cached[:60])}")
                            text = cached
                        elif text not in _logged_hooks:
                            _logged_hooks.add(text)
                            log.hook(f"[UI_TEXT] {repr(text[:80])}")
                        if cached == orig_text:
                            _remember_ui_widget(orig_text, self)
                try:
                    return _orig_set_text(self, text, scope=scope, substitute=substitute, update=update)
                except Exception as e:
                    log_once("SETTEXT_FAIL", f"set_text falhou (texto original): {e}")
                    try:
                        return _orig_set_text(self, orig_text, scope=scope, substitute=False, update=update)
                    except Exception:
                        return None
            Text.set_text = _patched_set_text
            _record_patch(Text, "set_text", _patched_set_text, _orig_set_text)
            log.hook("Hook OK: Text.set_text (traduz UI)")

            # Text.__init__: traduz texto na CRIACAO do widget (menus/botoes)
            _orig_text_init = Text.__init__
            def _patched_text_init(self, *args, **kwargs):
                if args and isinstance(args[0], str) and len(args[0]) > 3:
                    with _cache_lock:
                        is_trans = args[0] in _cache and _cache[args[0]] == args[0]
                    if not is_trans:
                        cached = _translate_text(args[0], blocking=False)
                        if cached != args[0]:
                            args = (cached,) + args[1:]
                elif 'text' in kwargs and isinstance(kwargs['text'], str) and len(kwargs['text']) > 3:
                    with _cache_lock:
                        is_trans = kwargs['text'] in _cache and _cache[kwargs['text']] == kwargs['text']
                    if not is_trans:
                        cached = _translate_text(kwargs['text'], blocking=False)
                        if cached != kwargs['text']:
                            kwargs['text'] = cached
                return _orig_text_init(self, *args, **kwargs)
            try:
                Text.__init__ = _patched_text_init
                _record_patch(Text, "__init__", _patched_text_init, _orig_text_init)
                log.hook("Hook OK: Text.__init__ (traduz UI na criacao)")
            except Exception as e:
                log.warn(f"Falha hook Text.__init__: {e}")
    except Exception as e:
        log.warn(f"Falha hooks Text: {e}")

    # 12. renpy.display.screen.show_screen (traduz what da screen 'say' usando cache)
    try:
        import renpy.display.screen
        _orig_show_screen = renpy.display.screen.show_screen
        def _patched_show_screen(name, *args, **kwargs):
            if name == "say" and 'what' in kwargs and isinstance(kwargs['what'], str) and len(kwargs['what']) > 3:
                w = kwargs['what']
                # Usa cache se ja traduzido (do_display ja populou); senao enfileira
                cached = _translate_text(w, blocking=False)
                if cached != w:
                    kwargs['what'] = cached
            log.hook(f"[SHOW_SCREEN] name={name}, who={repr(kwargs.get('who',''))[:60]}, what={repr(kwargs.get('what',''))[:120]}")
            return _orig_show_screen(name, *args, **kwargs)
        renpy.display.screen.show_screen = _patched_show_screen
        _record_patch(renpy.display.screen, "show_screen", _patched_show_screen, _orig_show_screen)
        log.hook("Hook OK: renpy.display.screen.show_screen (traduz say)")
    except Exception as e:
        log.warn(f"Falha hook show_screen: {e}")

    # 13. renpy.display.displayable.Displayable.__init__ (broad)
    try:
        import renpy.display.displayable
        original_disp_init = renpy.display.displayable.Displayable.__init__
        def patched_disp_init(self, *args, **kwargs):
            cls_name = type(self).__name__
            log_once(f"DISP_{cls_name}", f"Displayable criado: {cls_name}")
            return original_disp_init(self, *args, **kwargs)
        renpy.display.displayable.Displayable.__init__ = patched_disp_init
        _record_patch(renpy.display.displayable.Displayable, "__init__", patched_disp_init, original_disp_init)
        log.hook("Hook OK: Displayable.__init__")
    except Exception as e:
        log.warn(f"Falha hook Displayable: {e}")

    # 14. renpy.ui.text / textbutton / button / label - traduz strings de UI
    try:
        for _uiname in ["text", "button", "label", "vbutton", "textbutton", "imagebutton"]:
            _uifunc = getattr(renpy.ui, _uiname, None)
            if _uifunc:
                _orig_ui = _uifunc
                def _make_ui_patched(fname, orig):
                    def _patched(*args, **kwargs):
                        if args and isinstance(args[0], str) and len(args[0]) > 3:
                            with _cache_lock:
                                is_trans = args[0] in _cache and _cache[args[0]] == args[0]
                            if not is_trans:
                                cached = _translate_text(args[0], blocking=False)
                                if cached != args[0]:
                                    args = (cached,) + args[1:]
                                    if args[0] not in _logged_hooks:
                                        _logged_hooks.add(args[0])
                                        log.ok(f"UI_{fname}: {repr(args[0][:60])}")
                        elif 'text' in kwargs and isinstance(kwargs['text'], str) and len(kwargs['text']) > 3:
                            with _cache_lock:
                                is_trans = kwargs['text'] in _cache and _cache[kwargs['text']] == kwargs['text']
                            if not is_trans:
                                cached = _translate_text(kwargs['text'], blocking=False)
                                if cached != kwargs['text']:
                                    kwargs['text'] = cached
                                    if kwargs['text'] not in _logged_hooks:
                                        _logged_hooks.add(kwargs['text'])
                                        log.ok(f"UI_{fname}: {repr(kwargs['text'][:60])}")
                        return orig(*args, **kwargs)
                    return _patched
                _p = _make_ui_patched(_uiname.upper(), _orig_ui)
                setattr(renpy.ui, _uiname, _p)
                _record_patch(renpy.ui, _uiname, _p, _orig_ui)
                log.hook(f"Hook OK: renpy.ui.{_uiname}")
    except Exception as e:
        log.warn(f"Falha hook ui: {e}")

    # 15. renpy.exports.say no modulo exports
    try:
        import renpy.exports.sayexports
        original_sayexports = renpy.exports.sayexports.say
        def patched_sayexports(who, what, *args, **kwargs):
            log.hook(f"[SAYEXPORTS] what={repr(what)[:120]}")
            return original_sayexports(who, what, *args, **kwargs)
        renpy.exports.sayexports.say = patched_sayexports
        log.hook("Hook OK: renpy.exports.sayexports.say")
    except Exception as e:
        log.warn(f"Falha hook sayexports: {e}")

    # Heartbeat
    def _heartbeat():
        import time
        count = 0
        while True:
            time.sleep(5)
            count += 1
            _touch_session()
            log.hook(f"Heartbeat {count}: hook ativo")
    t = threading.Thread(target=_heartbeat, daemon=True)
    t.start()
    log.hook("Heartbeat iniciado (5s)")

    # Worker de traducao (inicia aqui p/ logar no console visivel)
    global _worker_thread_started
    if not _worker_thread_started:
        _worker_thread_started = True
        wt = threading.Thread(target=_worker_loop, daemon=True)
        wt.start()

    # Ponte segura worker -> UI para versoes sem invoke_in_main_thread.
    global _periodic_refresh_installed
    try:
        callbacks = getattr(renpy.config, "periodic_callbacks", None)
        if callbacks is not None and _periodic_ui_refresh not in callbacks:
            callbacks.append(_periodic_ui_refresh)
            _periodic_refresh_installed = True
            log.hook("Hook OK: periodic_callbacks (refresh de menus)")
    except Exception as e:
        log.warn(f"Falha instalar refresh periodico de UI: {e}")

    # Garante o servidor LibreTranslate embutido (redundancia: phase1 ja tentou)
    if PROVIDER == "local" and uat_lt is not None:
        try:
            threading.Thread(target=uat_lt.ensure_server, daemon=True).start()
        except Exception as e:
            log.warn(f"Falha LT ensure (fase2): {e}")

    import atexit
    atexit.register(_save_cache)

    # Anti-pickle: renpy.save/load restaura originais antes do pickle.
    _ensure_save_wrap()

    log.hook("Pronto. Aguardando dialogo...")

# --- Fases de inicializacao ---
_phase2_done = False

def phase1():
    """Fase 1: prepara o logger antes do init do jogo."""
    _touch_session()
    if SHOW_CONSOLE:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            if not kernel32.GetConsoleWindow():
                kernel32.AllocConsole()
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            try:
                log.reopen_console()
            except Exception:
                pass
        except Exception:
            pass
    # Garante o servidor LibreTranslate embutido (thread, nunca bloqueia o jogo)
    if PROVIDER == "local" and uat_lt is not None:
        try:
            threading.Thread(target=uat_lt.ensure_server, daemon=True).start()
            log.hook("LT embutido: garantindo servidor local (thread)")
        except Exception as e:
            log.warn(f"Falha iniciar LT manager: {e}")
    log.info("=== UAT Ren'Py Hook v2 (Fase 1) ===")
    log.info(f"Provider: {PROVIDER} | {SOURCE} -> {TARGET}")

def phase2():
    """Fase 2: instala hooks APOS todo o init do jogo (game ja carregou)."""
    global _phase2_done
    if _phase2_done:
        return
    _phase2_done = True
    log.info("=== UAT Ren'Py Hook v2 (Fase 2) ===")
    install_hook()

def start():
    phase1()
    phase2()

if __name__ == "__main__":
    start()
