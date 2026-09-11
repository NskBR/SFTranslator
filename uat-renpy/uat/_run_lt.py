import os
import sys
import json
import time
import glob
import threading
import subprocess
import urllib.request
import queue
import shutil
from pathlib import Path

os.environ.setdefault("LT_API_KEYS", "")
os.environ["PYTHONIOENCODING"] = "utf-8"

FROZEN = getattr(sys, "frozen", False)


def _exe_dir():
    """Pasta do executavel (frozen) ou do script (modo python)."""
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _find_uat_dir():
    """Acha a pasta uat/ (a que tem uat_config.json) subindo a arvore.
    Funciona com lt/ em qualquer lugar: raiz do jogo, subpasta, etc."""
    base = _exe_dir()
    # modo script: _run_lt.py mora dentro de uat/
    if not FROZEN and os.path.isfile(os.path.join(base, "uat_config.json")):
        return base
    p = base
    for _ in range(6):
        c = os.path.join(p, "uat")
        if os.path.isfile(os.path.join(c, "uat_config.json")):
            return c
        p = os.path.dirname(p)
    return os.path.join(os.path.dirname(base), "uat")


UAT_DIR = _find_uat_dir()


def _load_config():
    try:
        with open(os.path.join(UAT_DIR, "uat_config.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    path = os.path.join(UAT_DIR, "uat_config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _argos_code(code):
    value = str(code or "").strip().lower().replace("_", "-")
    if value in ("pt-br", "pb"):
        return "pb"
    if value in ("pt-pt", "pt"):
        return "pt"
    return value.split("-")[0]


def _config_code(code):
    return "pt-BR" if code == "pb" else code


def _safe_pair(source, target):
    return (source + "_" + target).replace("-", "_").replace("/", "_")


def _find_models_dir():
    """Modelos Argos embutidos. Caminhos possiveis:
    1) uat/lt/models      (lt/ colado dentro de uat/)
    2) <raiz>/lt/models   (pasta lt/ inteira colada na raiz do jogo)
    3) <raiz>/models      (conteudo de lt/ colado na raiz, exe junto do game)"""
    override = os.environ.get("UAT_MODELS_DIR")
    if override:
        return os.path.abspath(override)
    root = os.path.dirname(UAT_DIR)
    for c in (os.path.join(UAT_DIR, "lt", "models"),
              os.path.join(root, "lt", "models"),
              os.path.join(root, "models")):
        if os.path.isdir(os.path.join(c, "argos-translate")):
            return c
    # Diretorio modular padrao, mesmo antes do primeiro modelo ser baixado.
    return os.path.join(root, "models")


MODELS = _find_models_dir()
PACKAGES_DIR = os.path.join(MODELS, "argos-translate", "packages")
if MODELS:
    os.makedirs(PACKAGES_DIR, exist_ok=True)
    os.environ["XDG_DATA_HOME"] = MODELS
    os.environ["ARGOS_PACKAGES_DIR"] = os.path.join(MODELS, "argos-translate", "packages")
    try:
        from minisbd import models as _msbd
        _msbd.cache_dir = os.path.join(MODELS, "minisbd")
    except Exception:
        pass


def _installed_models():
    """Retorna modelos diretos encontrados, sem aceitar rotas por pivo."""
    found = {}
    if not os.path.isdir(PACKAGES_DIR):
        return found
    for entry in os.scandir(PACKAGES_DIR):
        if not entry.is_dir():
            continue
        metadata = os.path.join(entry.path, "metadata.json")
        try:
            with open(metadata, "r", encoding="utf-8") as f:
                data = json.load(f)
            source = _argos_code(data.get("from_code"))
            target = _argos_code(data.get("to_code"))
            if source and target:
                found[(source, target)] = {
                    "path": entry.path,
                    "version": str(data.get("package_version", "?")),
                    "from_name": data.get("from_name", source),
                    "to_name": data.get("to_name", target),
                }
        except Exception:
            continue
    return found


def _available_models(refresh=True):
    import argostranslate.package as package
    if refresh:
        print("\nAtualizando catalogo de modelos Argos...", flush=True)
        package.update_package_index()
    packages = package.get_available_packages()
    direct = {}
    for pkg in packages:
        source = _argos_code(getattr(pkg, "from_code", ""))
        target = _argos_code(getattr(pkg, "to_code", ""))
        if source and target and source != target:
            direct[(source, target)] = pkg
    return direct


def _language_names(packages):
    names = {"pb": "Portugues (Brasil)", "pt": "Portugues", "en": "English",
             "ja": "Japanese", "es": "Spanish", "fr": "French",
             "de": "German", "ko": "Korean", "zh": "Chinese"}
    for (source, target), pkg in packages.items():
        names[source] = getattr(pkg, "from_name", None) or names.get(source, source)
        names[target] = getattr(pkg, "to_name", None) or names.get(target, target)
    return names


def _choose_cli_grid(title, options, formatter):
    """Grade paginada no proprio console, controlada por teclado."""
    import msvcrt

    original = list(options)
    filtered = list(options)
    selected = 0
    query = ""

    while True:
        width = shutil.get_terminal_size((100, 30)).columns
        columns = 3 if width >= 84 else 2
        cell_width = max(20, min(32, (width - 4) // columns))
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

        print("\x1b[2J\x1b[H", end="")
        print("=" * min(width, 100))
        print("  " + title)
        print("=" * min(width, 100))
        print("  Setas/WASD: navegar   ENTER: selecionar   /: buscar   ESC/Q: voltar")
        if query:
            print("  Filtro: {!r}   Resultados: {}".format(query, len(filtered)))
        else:
            print("  Pagina {}/{}   Opcoes: {}".format(page + 1, total_pages, len(filtered)))
        print()

        for row in range(rows):
            cells = []
            for column in range(columns):
                local = row * columns + column
                absolute = start + local
                if local >= len(visible):
                    cells.append(" " * cell_width)
                    continue
                label = formatter(visible[local]).replace("\n", " ")
                label = label[:cell_width - 5]
                marker = ">" if absolute == selected else " "
                cells.append((" {} {:<{}}".format(marker, label, cell_width - 3))[:cell_width])
            print("".join(cells).rstrip())

        if not filtered:
            print("  Nenhum idioma encontrado. Pressione / para buscar novamente.")

        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            ext = msvcrt.getwch()
            key = {"H": "up", "P": "down", "K": "left", "M": "right",
                   "I": "pageup", "Q": "pagedown"}.get(ext, "")
        else:
            key = key.lower()

        if key in ("\r", "\n") and filtered:
            print()
            return filtered[selected]
        if key in ("\x1b", "q"):
            print()
            return None
        if key in ("/", "f"):
            print("\nBuscar idioma (nome ou codigo): ", end="", flush=True)
            query = input().strip().lower()
            filtered = [option for option in original
                        if query in formatter(option).lower()]
            selected = 0
            continue
        if key in ("up", "w"):
            selected -= columns
        elif key in ("down", "s"):
            selected += columns
        elif key in ("left", "a"):
            selected -= 1
        elif key in ("right", "d"):
            selected += 1
        elif key == "pageup":
            selected -= page_size
        elif key == "pagedown":
            selected += page_size


def _choose(title, options, formatter):
    if os.name == "nt" and sys.stdin.isatty():
        return _choose_cli_grid(title, options, formatter)
    print("\n" + title)
    for index, option in enumerate(options, 1):
        print("  [{:>2}] {}".format(index, formatter(option)))
    print("  [ 0] Voltar")
    while True:
        raw = input("\nEscolha: ").strip()
        if raw == "0":
            return None
        try:
            value = int(raw)
            if 1 <= value <= len(options):
                return options[value - 1]
        except ValueError:
            pass
        print("Opcao invalida.")


def _install_model(pkg, source, target):
    import argostranslate.package as package
    print("\nBaixando modelo {} -> {}...".format(source, target), flush=True)
    downloaded = pkg.download()
    print("Download concluido. Instalando...", flush=True)
    package.install_from_path(downloaded)
    if (source, target) not in _installed_models():
        raise RuntimeError("o Argos nao reconheceu o modelo depois da instalacao")
    print("[OK] Modelo instalado em: " + PACKAGES_DIR)


def _activate_pair(source, target):
    cfg = _load_config()
    cfg["provider"] = "local"
    cfg["source_language"] = _config_code(source)
    cfg["target_language"] = _config_code(target)
    pair = _safe_pair(source, target)
    cfg["cache_file"] = "caches/uat_cache_{}.json".format(pair)
    cfg["words_file"] = "caches/uat_words_{}.json".format(pair)
    _save_config(cfg)


def _configure_languages_cli(available=None):
    if available is None:
        try:
            available = _available_models(refresh=True)
        except Exception as e:
            print("\n[ERRO] Nao foi possivel carregar o catalogo: {}".format(e))
            input("Pressione ENTER para voltar...")
            return False
    names = _language_names(available)
    sources = sorted({source for source, _target in available},
                     key=lambda code: names.get(code, code).lower())
    source = _choose("Idioma original do jogo:", sources,
                     lambda code: "{} ({})".format(names.get(code, code), code))
    if source is None:
        return False
    targets = sorted({target for src, target in available if src == source},
                     key=lambda code: names.get(code, code).lower())
    target = _choose("Traduzir para:", targets,
                     lambda code: "{} ({})".format(names.get(code, code), code))
    if target is None:
        return False
    pkg = available.get((source, target))
    if pkg is None:
        print("\n[ERRO] Nao existe modelo direto para esse par.")
        input("Pressione ENTER para voltar...")
        return False
    if (source, target) not in _installed_models():
        answer = input("\nModelo {} -> {} nao instalado. Baixar agora? [S/n]: ".format(
            names.get(source, source), names.get(target, target))).strip().lower()
        if answer not in ("", "s", "sim", "y", "yes"):
            return False
        try:
            _install_model(pkg, source, target)
        except Exception as e:
            print("\n[ERRO] Falha baixar/instalar modelo: {}".format(e))
            input("Pressione ENTER para voltar...")
            return False
    _activate_pair(source, target)
    print("\n[OK] Configuracao ativada: {} -> {}".format(
        names.get(source, source), names.get(target, target)))
    input("Pressione ENTER para voltar ao menu...")
    return True


def _configure_languages_gui(available):
    """Seletor grafico pesquisavel; retorna True quando ativa um par."""
    # Mantido apenas para compatibilidade de codigo antigo. O launcher atual
    # usa exclusivamente a grade CLI e nao empacota Tkinter.
    tk = __import__("tkinter")
    ttk = __import__("tkinter.ttk", fromlist=["ttk"])
    messagebox = __import__("tkinter.messagebox", fromlist=["messagebox"])

    names = _language_names(available)
    installed = _installed_models()
    state = {"source": None, "target": None, "success": False, "busy": False}
    worker_results = queue.Queue()
    bg = "#101820"
    panel = "#18252e"
    card = "#22333d"
    card_active = "#2374ab"
    text = "#f3f7f9"
    muted = "#9eb1bd"
    accent = "#45b6fe"

    root = tk.Tk()
    root.title("UAT - Configurar idiomas")
    root.geometry("980x700")
    root.minsize(820, 580)
    root.configure(bg=bg)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("UAT.Horizontal.TProgressbar", troughcolor=panel,
                    background=accent, bordercolor=panel, lightcolor=accent,
                    darkcolor=accent)

    header = tk.Frame(root, bg=bg)
    header.pack(fill="x", padx=28, pady=(22, 12))
    tk.Label(header, text="Configurar tradução", bg=bg, fg=text,
             font=("Segoe UI Semibold", 22)).pack(anchor="w")
    tk.Label(header, text="Escolha um par direto disponível no catálogo Argos.",
             bg=bg, fg=muted, font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

    columns = tk.Frame(root, bg=bg)
    columns.pack(fill="both", expand=True, padx=22, pady=8)
    columns.grid_columnconfigure(0, weight=1, uniform="lang")
    columns.grid_columnconfigure(1, weight=1, uniform="lang")
    columns.grid_rowconfigure(0, weight=1)

    def make_grid(parent, column, title):
        outer = tk.Frame(parent, bg=panel, highlightthickness=1,
                         highlightbackground="#2b414d")
        outer.grid(row=0, column=column, sticky="nsew", padx=7)
        tk.Label(outer, text=title, bg=panel, fg=text,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=15, pady=(14, 7))
        search = tk.StringVar()
        entry = tk.Entry(outer, textvariable=search, bg="#0f1a20", fg=text,
                         insertbackground=text, relief="flat", font=("Segoe UI", 10))
        entry.pack(fill="x", padx=14, ipady=8, pady=(0, 10))
        canvas = tk.Canvas(outer, bg=panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=panel)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 10))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        return search, body

    source_search, source_body = make_grid(columns, 0, "1. Idioma do jogo")
    target_search, target_body = make_grid(columns, 1, "2. Traduzir para")
    source_buttons = {}
    target_buttons = {}

    footer = tk.Frame(root, bg=bg)
    footer.pack(fill="x", padx=29, pady=(8, 22))
    status_var = tk.StringVar(value="Selecione o idioma original do jogo.")
    status = tk.Label(footer, textvariable=status_var, bg=bg, fg=muted,
                      font=("Segoe UI", 10), anchor="w")
    status.pack(fill="x", pady=(0, 8))
    progress = ttk.Progressbar(footer, mode="indeterminate", style="UAT.Horizontal.TProgressbar")
    actions = tk.Frame(footer, bg=bg)
    actions.pack(fill="x")
    close_btn = tk.Button(actions, text="Cancelar", command=root.destroy, bg=card,
                          fg=text, activebackground="#314853", activeforeground=text,
                          relief="flat", padx=20, pady=9, font=("Segoe UI Semibold", 10))
    close_btn.pack(side="right")
    activate_btn = tk.Button(actions, text="Selecione os idiomas", state="disabled",
                             bg=card_active, fg="white", disabledforeground="#7d929e",
                             activebackground="#2c8bc9", activeforeground="white",
                             relief="flat", padx=22, pady=9, font=("Segoe UI Semibold", 10))
    activate_btn.pack(side="right", padx=(0, 10))

    def button_text(code):
        return "{}\n{}".format(names.get(code, code), code)

    def paint_buttons(buttons, selected):
        for code, button in buttons.items():
            button.configure(bg=card_active if code == selected else card)

    def refresh_action():
        source, target = state["source"], state["target"]
        if not source or not target:
            activate_btn.configure(text="Selecione os idiomas", state="disabled")
            return
        present = (source, target) in installed
        activate_btn.configure(text="Ativar modelo" if present else "Baixar e ativar",
                               state="normal")
        status_var.set("Modelo {} → {} {}.".format(
            names.get(source, source), names.get(target, target),
            "já está instalado" if present else "será baixado"))

    def render_targets(*_args):
        for child in target_body.winfo_children():
            child.destroy()
        target_buttons.clear()
        source = state["source"]
        query = target_search.get().strip().lower()
        targets = sorted({target for src, target in available if src == source},
                         key=lambda code: names.get(code, code).lower()) if source else []
        targets = [code for code in targets if query in names.get(code, code).lower()
                   or query in code.lower()]
        for index, code in enumerate(targets):
            def choose(value=code):
                state["target"] = value
                paint_buttons(target_buttons, value)
                refresh_action()
            button = tk.Button(target_body, text=button_text(code), command=choose,
                               justify="left", anchor="w", bg=card, fg=text,
                               activebackground=card_active, activeforeground="white",
                               relief="flat", padx=11, pady=9, font=("Segoe UI", 9))
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=5, pady=5)
            target_body.grid_columnconfigure(index % 2, weight=1)
            target_buttons[code] = button
        paint_buttons(target_buttons, state["target"])

    def render_sources(*_args):
        for child in source_body.winfo_children():
            child.destroy()
        source_buttons.clear()
        query = source_search.get().strip().lower()
        sources = sorted({source for source, _target in available},
                         key=lambda code: names.get(code, code).lower())
        sources = [code for code in sources if query in names.get(code, code).lower()
                   or query in code.lower()]
        for index, code in enumerate(sources):
            def choose(value=code):
                state["source"] = value
                state["target"] = None
                paint_buttons(source_buttons, value)
                status_var.set("Agora escolha o idioma de destino.")
                render_targets()
                refresh_action()
            button = tk.Button(source_body, text=button_text(code), command=choose,
                               justify="left", anchor="w", bg=card, fg=text,
                               activebackground=card_active, activeforeground="white",
                               relief="flat", padx=11, pady=9, font=("Segoe UI", 9))
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=5, pady=5)
            source_body.grid_columnconfigure(index % 2, weight=1)
            source_buttons[code] = button
        paint_buttons(source_buttons, state["source"])

    def finish_ok(source, target):
        state["busy"] = False
        state["success"] = True
        progress.stop()
        progress.pack_forget()
        status_var.set("Configuração ativada: {} → {}".format(
            names.get(source, source), names.get(target, target)))
        activate_btn.configure(text="Ativado", state="disabled")
        close_btn.configure(text="Concluir")
        messagebox.showinfo("UAT", "Modelo ativado com sucesso.", parent=root)

    def finish_error(error):
        state["busy"] = False
        progress.stop()
        progress.pack_forget()
        activate_btn.configure(state="normal")
        status_var.set("Falha ao preparar o modelo.")
        messagebox.showerror("UAT", "Falha ao baixar/instalar:\n{}".format(error), parent=root)

    def poll_worker():
        try:
            result = worker_results.get_nowait()
        except queue.Empty:
            root.after(100, poll_worker)
            return
        kind = result[0]
        close_btn.configure(state="normal")
        if kind == "ok":
            finish_ok(result[1], result[2])
        else:
            finish_error(result[1])
        root.after(100, poll_worker)

    def activate():
        if state["busy"]:
            return
        source, target = state["source"], state["target"]
        if not source or not target:
            return
        state["busy"] = True
        activate_btn.configure(state="disabled")
        close_btn.configure(state="disabled")
        progress.pack(fill="x", pady=(0, 12), before=actions)
        progress.start(10)
        status_var.set("Preparando {} → {}...".format(
            names.get(source, source), names.get(target, target)))

        def work():
            try:
                if (source, target) not in _installed_models():
                    _install_model(available[(source, target)], source, target)
                _activate_pair(source, target)
                worker_results.put(("ok", source, target))
            except Exception as e:
                worker_results.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    activate_btn.configure(command=activate)
    source_search.trace_add("write", render_sources)
    target_search.trace_add("write", render_targets)
    render_sources()
    root.after(100, poll_worker)
    root.mainloop()
    return state["success"]


def _configure_languages():
    try:
        available = _available_models(refresh=True)
    except Exception as e:
        print("\n[ERRO] Nao foi possivel carregar o catalogo: {}".format(e))
        input("Pressione ENTER para voltar...")
        return False
    return _configure_languages_cli(available)


def _show_installed_models():
    installed = _installed_models()
    print("\nMODELOS INSTALADOS")
    print("-" * 64)
    if not installed:
        print("Nenhum modelo instalado.")
    for (source, target), info in sorted(installed.items()):
        print("  {} -> {}  versao {}".format(
            info["from_name"], info["to_name"], info["version"]))
    input("\nPressione ENTER para voltar...")


def _current_pair():
    cfg = _load_config()
    return _argos_code(cfg.get("source_language", "en")), _argos_code(
        cfg.get("target_language", "pt-BR"))


def _read_launcher_key():
    """Le uma tecla no console Windows; usa input normal em testes/pipes."""
    if os.name == "nt" and sys.stdin.isatty():
        import msvcrt
        print("\nOpcao: ", end="", flush=True)
        key = msvcrt.getwch()
        if key in ("\r", "\n"):
            print()
            return ""
        if key == "\x1b":
            print("ESC")
            return "esc"
        print(key)
        return key.strip().lower()
    return input("\nOpcao: ").strip().lower()


def _launcher_menu(game):
    while True:
        source, target = _current_pair()
        installed = _installed_models()
        info = installed.get((source, target))
        has_model = (source, target) in installed
        print("\n" + "=" * 64)
        print("  UAT - Tradutor modular para Ren'Py")
        print("=" * 64)
        print("  Jogo: " + (os.path.basename(game) if game else "nao encontrado"))
        print("  Configuracao atual: {} -> {}".format(source, target))
        print("  Modelo: " + ("instalado e pronto" if has_model else "NAO INSTALADO"))
        print("\n  [ENTER] Iniciar tradutor e abrir o jogo")
        print("  [C]     Alterar idiomas / baixar modelo")
        print("  [M]     Ver modelos instalados")
        print("  [ESC/Q] Sair")
        choice = _read_launcher_key()
        if choice == "":
            if not game:
                print("\n[ERRO] Nenhum executavel de jogo foi encontrado.")
                continue
            if not has_model:
                print("\n[ERRO] O modelo direto {} -> {} nao esta instalado.".format(source, target))
                continue
            return True
        if choice == "c":
            _configure_languages()
        elif choice == "m":
            _show_installed_models()
        elif choice in ("q", "esc", "sair"):
            return False
        else:
            print("Opcao invalida.")


def _load_only():
    """Idiomas a pre-carregar, a partir da config do UAT."""
    langs = set()
    try:
        with open(os.path.join(UAT_DIR, "uat_config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        src = cfg.get("source_language", "en")
        tgt = cfg.get("target_language", "pt-BR")
        langs.add(_argos_code(src))
        langs.add(_argos_code(tgt))
        if cfg.get("flow_mode") == "chain":
            langs.add(_argos_code(cfg.get("intermediate_language", "en")))
    except Exception:
        pass
    return ",".join(sorted(langs))


def _endpoint():
    try:
        with open(os.path.join(UAT_DIR, "uat_config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("local", {}).get("endpoint", "http://127.0.0.1:5000/translate")
    except Exception:
        return "http://127.0.0.1:5000/translate"


def _port():
    p = os.environ.get("LT_PORT")
    if p:
        try:
            return int(p)
        except Exception:
            pass
    from urllib.parse import urlparse
    try:
        return urlparse(_endpoint()).port or 5000
    except Exception:
        return 5000


def _server_ready(timeout=1.5):
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(_endpoint(), method="GET"), timeout=timeout)
        s = r.getcode()
        r.close()
        return (s or 500) < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def _run_server():
    """Sobe o servidor LibreTranslate (bloqueia)."""
    from libretranslate import main
    sys.argv = [
        "libretranslate", "--host", "127.0.0.1",
        "--port", str(_port()),
        "--load-only", _load_only(),
    ]
    main()


def _find_game_exe():
    """Procura o exe do jogo subindo a arvore a partir do lt (ate 3 niveis).
    Ignora o proprio lt.exe, python/renpy e afins."""
    base = _exe_dir()
    self_name = os.path.basename(sys.executable).lower()
    banned = {"lt.exe", "python.exe", "pythonw.exe", "renpy.exe",
              "pyinstaller.exe", "pyinstaller_windows.exe"}
    p = base
    for _ in range(3):
        try:
            exes = [e for e in glob.glob(os.path.join(p, "*.exe"))
                    if os.path.basename(e).lower() not in banned
                    and os.path.basename(e).lower() != self_name]
        except Exception:
            exes = []
        if exes:
            # Prefere o exe 64 bits padrao (Ren'Py gera "Jogo.exe" e "Jogo-32.exe")
            exes.sort(key=lambda e: ("-32" in os.path.basename(e).lower(),
                                     os.path.basename(e).lower()))
            return exes[0], p
        p = os.path.dirname(p)
    return None, None


def _launcher_main():
    game, gdir = _find_game_exe()
    if not _launcher_menu(game):
        return
    print("\nIniciando o LibreTranslate embutido...")
    print("  uat/     -> " + UAT_DIR)
    print("  modelos  -> " + MODELS)
    t = threading.Thread(target=_run_server, daemon=True)
    t.start()
    t0 = time.time()
    while time.time() - t0 < 180:
        if _server_ready():
            print("[OK] Servidor local no ar em %.0fs." % (time.time() - t0), flush=True)
            break
        time.sleep(1)
    else:
        print("[!] Servidor nao respondeu em 180s (veja uat/UAlogs/lt_server.log)", flush=True)
    print("[OK] Abrindo o jogo: " + os.path.basename(game), flush=True)
    print("     (feche o jogo para encerrar este console)", flush=True)
    subprocess.run([game], cwd=gdir)
    print("[OK] Jogo fechado. Encerrando servidor...", flush=True)
    os._exit(0)


def main():
    # Double-click / "abrir o lt.exe" -> servidor + inicia o jogo.
    # "lt.exe __server__" (usado pelo uat_hook) -> so o servidor.
    if "__launcher_test__" in sys.argv:
        _launcher_menu(None)
    elif FROZEN and "__server__" not in sys.argv:
        _launcher_main()
    else:
        _run_server()


if __name__ == "__main__":
    main()
