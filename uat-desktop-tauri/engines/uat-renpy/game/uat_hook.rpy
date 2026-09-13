init python:
    import os
    import sys

    def _uat_find_dir():
        """Localiza a pasta 'uat/' do pack automaticamente, para o modo
        'jogar na pasta do jogo e abrir'. Procura por uma pasta que contenha
        uat_hook.py (o motor), em:
          1. <jogo>/uat                       (layout padrao da instalacao)
          2. <jogo>/game/uat                  (caso tenha sido jogada pra dentro)
          3. <jogo>/*/uat                     (pack em subpasta, ex: UAT-Pack/uat)
          4. <jogo>/*                          (a propria pasta do pack chamada uat)
        Se nada achar, cai no layout padrao <jogo>/uat."""
        base = os.path.abspath(os.path.join(config.gamedir, ".."))
        cands = [
            os.path.join(base, "uat"),
            os.path.join(config.gamedir, "uat"),
        ]
        try:
            for entry in os.listdir(base):
                ed = os.path.join(base, entry)
                if os.path.isdir(ed):
                    cands.append(os.path.join(ed, "uat"))
                    cands.append(ed)
        except Exception:
            pass
        # parentes acima (instalacao num pacote Extern/../uat etc.)
        p = base
        for _ in range(4):
            p = os.path.dirname(p)
            c = os.path.join(p, "uat")
            if os.path.isdir(c):
                cands.insert(0, c)
        for cand in cands:
            if os.path.isfile(os.path.join(cand, "uat_hook.py")):
                return cand
        return os.path.join(base, "uat")

    _uat_dir = _uat_find_dir()
    if _uat_dir not in sys.path:
        sys.path.insert(0, _uat_dir)

    # Detecta Python 3.6+ (com f-strings e urllib.request) ou Python 2.7 (legado)
    if sys.version_info[0] >= 3 and sys.version_info[1] >= 6:
        if 'uat_hook' in sys.modules:
            del sys.modules['uat_hook']
        import uat_hook
        _mod = uat_hook
    else:
        for k in list(sys.modules):
            if 'uat_hook' in k:
                del sys.modules[k]
        import uat_hook_legacy
        _mod = uat_hook_legacy
        sys.modules['uat_hook'] = _mod

    _mod.phase1()
    config.python_callbacks.append(_mod.phase2)