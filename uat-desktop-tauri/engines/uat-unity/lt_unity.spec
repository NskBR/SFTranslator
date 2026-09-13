# -*- mode: python ; coding: utf-8 -*-
# lt.exe = uat_unity.py congelado (servidor XUnity + wizard install).
# Modelo Argos NAO e embalado aqui: uat_unity.py aponta ARGOS_PACKAGES_DIR para
# UAT-UNITY/models/.../packages (no disco) via env vars -> exe le o modelo do jogo.
import os
from PyInstaller.utils.hooks import collect_all

HERE = os.path.dirname(os.path.abspath(SPEC))

datas = []
binaries = []
hiddenimports = [
    'argostranslate', 'argostranslate.package', 'argostranslate.translate',
    'argostranslate.settings', 'argostranslate.utils',
]
for mod in ['argostranslate']:
    d, b, h = collect_all(mod)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    [os.path.join(HERE, 'uat_unity.py')],
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='lt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='lt',
)
