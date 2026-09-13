#!/usr/bin/env python
"""
INSTALADOR do UAT (Universal Auto Translator) para jogos Ren'Py.

Uso:
    python install_uat.py "C:/caminho/para/o/jogo" [src=en] [tgt=pt] [prov=google_free]
    python install_uat.py "C:/caminho/para/o/jogo" prov=local endpoint=http://localhost:5000/translate
    python install_uat.py "C:/caminho/para/o/jogo" prov=local --setup-lt

O script:
    1. Verifica se a pasta do jogo tem 'game/'
    2. Copia a pasta 'uat/' para a raiz do jogo
    3. Copia lt.exe + _internal/ + models/ para a raiz do jogo (lt.exe
       fica na MESMA pasta do exe do game)
    4. Copia 'uat_hook.rpy' para game/
    5. (opcional) ajusta idiomas/provider no uat_config.json
    6. (opcional) --setup-lt  -> instala e aquece o LibreTranslate embutido AGORA

Providers:
    google_free  -> Google Translate (web, sem chave) - pode dar rate limit
    google_v2    -> Google Translate v2 (web)
    deepl_free   -> DeepL free (pode dar 429)
    local        -> API local (LibreTranslate embutido) - sem rate limit

Com prov=local o proprio UAT sobe o servidor: primeiro tenta o exe
embutido (lt.exe na raiz, gerado por build_lt.py); senao usa um venv
local (uat/.lt-venv) e instala o libretranslate sozinho na primeira vez.
Depois de instalado, abra o jogo normalmente (ou use lt.exe da raiz, que
sobe o tradutor e abre o jogo). Veja tambem uat/UAlogs/lt_server.log.
"""
import os
import sys
import shutil
import json
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

def find_game_dir(arg):
    p = os.path.abspath(arg)
    if os.path.isdir(os.path.join(p, "game")):
        return p
    # Tenta subpastas
    for root, dirs, files in os.walk(p):
        if "game" in dirs and (os.path.exists(os.path.join(root, "game", "script.rpy")) or
           os.path.exists(os.path.join(root, "game", "options.rpy"))):
            return root
    return None

def main():
    if len(sys.argv) < 2:
        print("Uso: python install_uat.py \"caminho/do/jogo\" [src=en] [tgt=pt] [prov=google_free]")
        print("     Ou: python install_uat.py \"caminho/do/jogo\" prov=local endpoint=http://localhost:5000/translate")
        sys.exit(1)

    game = find_game_dir(sys.argv[1])
    if not game:
        print("[ERRO] Pasta do jogo nao encontrada (precisa ter 'game/').")
        sys.exit(1)

    print(f"[OK] Jogo encontrado: {game}")

    setup_lt = "--setup-lt" in sys.argv
    argv = [a for a in sys.argv if a != "--setup-lt"]

    # 1. Copia pasta uat/
    src_uat = os.path.join(HERE, "uat")
    dst_uat = os.path.join(game, "uat")
    if os.path.exists(dst_uat):
        print("[AVISO] Pasta 'uat/' ja existe. Sobrescrevendo hook...")
    _ignore = shutil.ignore_patterns(".lt-venv", "__pycache__", "*.pyc", "build")
    shutil.copytree(src_uat, dst_uat, dirs_exist_ok=True, ignore=_ignore)
    print(f"[OK] Pasta 'uat/' copiada para {dst_uat}")

    # 1b. Copia lt.exe + _internal/ + models/ (raiz do pack) para a RAIZ do jogo:
    #     lt.exe fica na MESMA PASTA do exe do game.
    for item in ("lt.exe", "_internal", "models"):
        src_item = os.path.join(HERE, item)
        dst_item = os.path.join(game, item)
        if not os.path.exists(src_item):
            print(f"[AVISO] Nao achei '{item}' no pack. Rode antes: python build_lt.py")
            continue
        if os.path.isdir(src_item):
            shutil.copytree(src_item, dst_item, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "build"))
        else:
            shutil.copy2(src_item, dst_item)
    print(f"[OK] 'lt.exe' + '_internal/' + 'models/' copiados para a raiz: {game}")
    print(f"     lt.exe fica na mesma pasta do exe do game: {os.path.join(game, 'lt.exe')}")

    # 2. Copia uat_hook.rpy para game/
    src_rpy = os.path.join(HERE, "game", "uat_hook.rpy")
    dst_rpy = os.path.join(game, "game", "uat_hook.rpy")
    shutil.copy2(src_rpy, dst_rpy)
    print(f"[OK] 'uat_hook.rpy' copiado para {dst_rpy}")

    # 3. Ajusta idiomas/provider se passados
    src_cfg = os.path.join(dst_uat, "uat_config.json")
    cfg = {}
    if os.path.exists(src_cfg):
        with open(src_cfg, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    changed = False
    local_cfg = cfg.get("local", {})
    local_changed = False
    for a in argv[2:]:
        if a.startswith("src="):
            cfg["source_language"] = a[4:]
            changed = True
        elif a.startswith("tgt="):
            cfg["target_language"] = a[4:]
            changed = True
        elif a.startswith("prov="):
            cfg["provider"] = a[5:]
            changed = True
        elif a.startswith("endpoint="):
            local_cfg["endpoint"] = a[10:]
            local_changed = True
        elif a.startswith("apikey="):
            local_cfg["api_key"] = a[8:]
            local_changed = True
    if local_changed:
        cfg["local"] = local_cfg
        changed = True
    if changed:
        with open(src_cfg, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        prov = cfg.get("provider")
        print(f"[OK] Config: {cfg.get('source_language')} -> {cfg.get('target_language')} ({prov})")
        if prov == "local":
            print(f"     Endpoint local: {local_cfg.get('endpoint', 'http://localhost:5000/translate')}")

    print("\n[PRONTO] Instalacao concluida!")
    print("  Para abrir o jogo COM traducao local: use o " + os.path.join(game, "lt.exe"))
    print("  (sobe o tradutor sozinho e abre o jogo - lt.exe fica ao lado do exe do game)")
    print("  Ou abra o jogo normalmente: o UAT sobe o lt.exe automaticamente.")
    print("  Cache fica em 'uat/uat_cache.json' (reaproveita nas proximas execucoes).")

    # --setup-lt: instala e aquece o LibreTranslate embutido AGORA
    if setup_lt:
        if cfg.get("provider") != "local":
            print("[AVISO] --setup-lt dado mas provider != 'local'. Ignorando.")
        else:
            uat_lt_py = os.path.join(dst_uat, "uat_lt.py")
            print("\n[OK] Preparando servidor local (instala libretranslate + warmup)...")
            r = subprocess.run([sys.executable, uat_lt_py, "--setup-lt"])
            if r.returncode != 0:
                print("[AVISO] Setup do servidor local falhou. Rode manualmente:")
                print("        python \"%s\" --setup-lt" % uat_lt_py)
            else:
                print("[OK] Servidor local pronto. O jogo vai abrir tudo traduzido.")

if __name__ == "__main__":
    main()
