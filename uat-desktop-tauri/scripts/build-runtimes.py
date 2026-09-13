"""Build the application-owned Windows runtimes; never copy user translation models."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]
ENGINES = APP / "engines"
OUTPUT = APP / "src-tauri/resources/runtimes"
WORK = APP / "src-tauri/target/runtime-build"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    # Sentence splitting is part of the engine, not an on-demand game dependency.
    from minisbd import models
    models.cache_dir = str(OUTPUT / "minisbd")
    models.download_models(output=print)
    for engine, source, modules in [
        ("renpy", ENGINES / "uat-renpy/uat/_run_lt.py", ["libretranslate", "argostranslate", "argostranslatefiles", "minisbd", "ctranslate2", "sentencepiece", "onnxruntime"]),
        ("unity", ENGINES / "uat-unity/uat_unity.py", ["argostranslate", "minisbd", "ctranslate2", "sentencepiece", "onnxruntime", "langdetect"]),
    ]:
        destination = OUTPUT / engine
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--name", "lt",
                   "--distpath", str(destination), "--workpath", str(WORK / engine), "--specpath", str(WORK / engine)]
        for module in modules:
            command += ["--collect-all", module]
        command += ["--copy-metadata", "libretranslate", "--copy-metadata", "argos-translate-lt", str(source)]
        subprocess.run(command, check=True, cwd=APP)
        # The Tauri layout has one stable directory per adapter.
        staged = destination / "lt"
        if not staged.resolve().is_relative_to(OUTPUT.resolve()):
            raise RuntimeError("Runtime staging escaped the build output directory")
        shutil.copytree(staged, destination, dirs_exist_ok=True)
        shutil.rmtree(staged)
        if engine == "renpy":
            for directory in ("uat", "game"):
                shutil.copytree(ENGINES / "uat-renpy" / directory, destination / directory,
                                dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "UAlogs", "caches"))
    (OUTPUT / "manifest.json").write_text(json.dumps({"version": 1, "engines": ["renpy", "unity"]}), encoding="utf-8")


if __name__ == "__main__":
    main()
