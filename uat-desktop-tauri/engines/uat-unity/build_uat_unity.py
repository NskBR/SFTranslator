#!/usr/bin/env python
"""Gera o pack portatil UAT-Unity em dist/UAT-Unity/."""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(HERE, 'build')
DIST_DIR = os.path.join(HERE, 'dist')
STAGED_DIR = os.path.join(DIST_DIR, 'lt')
FINAL_DIR = os.path.join(DIST_DIR, 'UAT-Unity')

COLLECT_ALL = ['argostranslate', 'minisbd', 'stanza', 'sentencepiece', 'langdetect']
HIDDEN_IMPORTS = [
    'argostranslate.package', 'argostranslate.translate',
    'argostranslate.settings', 'argostranslate.utils',
]


def run(command):
    print('>> ' + ' '.join(command), flush=True)
    result = subprocess.run(command, cwd=HERE)
    if result.returncode:
        raise SystemExit(result.returncode)


def build():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print('[ERRO] PyInstaller nao instalado. Rode: python -m pip install pyinstaller')
        return 1

    for path in (BUILD_DIR, STAGED_DIR, FINAL_DIR):
        if os.path.isdir(path):
            shutil.rmtree(path)

    command = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir',
        '--name', 'lt', '--distpath', DIST_DIR, '--workpath', BUILD_DIR,
        '--specpath', BUILD_DIR,
    ]
    for module in COLLECT_ALL:
        command += ['--collect-all', module]
    for module in HIDDEN_IMPORTS:
        command += ['--hidden-import', module]
    command.append(os.path.join(HERE, 'uat_unity.py'))
    run(command)

    if not os.path.isfile(os.path.join(STAGED_DIR, 'lt.exe')):
        print('[ERRO] PyInstaller nao gerou dist/lt/lt.exe')
        return 1
    os.replace(STAGED_DIR, FINAL_DIR)

    for name in ('models',):
        source = os.path.join(HERE, name)
        if os.path.isdir(source):
            shutil.copytree(source, os.path.join(FINAL_DIR, name), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('unity_uat_config.json', 'launch_unity.bat', 'INSTALAR.txt'):
        source = os.path.join(HERE, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(FINAL_DIR, name))

    print('\n[OK] Pack portatil gerado em: ' + FINAL_DIR)
    print('     Copie a pasta UAT-Unity para dentro da raiz do jogo e abra lt.exe.')
    return 0


if __name__ == '__main__':
    raise SystemExit(build())
