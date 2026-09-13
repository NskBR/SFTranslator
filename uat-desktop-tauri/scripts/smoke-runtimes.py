"""Exercise both frozen servers with real models, outside the source tree."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def translate(port, text, source, target):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/translate",
        data=json.dumps({"q": text, "source": source, "target": target, "format": "text"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)["translatedText"]
    if not result or result == text:
        raise RuntimeError(f"Translation failed for {source} -> {target}: {result!r}")
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True, type=Path)
    parser.add_argument("--runtimes", type=Path, default=Path(__file__).resolve().parents[1] / "src-tauri/resources/runtimes")
    args = parser.parse_args()
    root = args.runtimes.resolve()
    for engine in ("renpy", "unity"):
        with tempfile.TemporaryDirectory(prefix="sftranslator-smoke-") as temporary:
            game = Path(temporary)
            state = game / ("uat" if engine == "renpy" else "uat-unity")
            state.mkdir()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            config = {"source_language": "ja", "target_language": "pb", "flow_mode": "chain",
                      "intermediate_language": "en", "server": {"port": port},
                      "local": {"endpoint": f"http://127.0.0.1:{port}/translate"}}
            (state / ("uat_config.json" if engine == "renpy" else "unity_uat_config.json")).write_text(json.dumps(config))
            env = dict(os.environ, UAT_GAME_DIR=str(game), UAT_STATE_DIR=str(state),
                       UAT_MODELS_DIR=str(args.models.resolve()), UAT_SBD_DIR=str(root / "minisbd"),
                       SFTRANSLATOR_MANAGED_RUNTIME="1", LT_PORT=str(port), PYTHONIOENCODING="utf-8")
            env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            with (game / "server.log").open("w+", encoding="utf-8", errors="replace") as log:
                process = subprocess.Popen([str(root / engine / "lt.exe"), "__server__"], cwd=state,
                    env=env, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    for _ in range(180):
                        if process.poll() is not None:
                            raise RuntimeError(f"{engine} exited: {process.returncode}")
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                                break
                        except OSError:
                            time.sleep(0.5)
                    else:
                        raise RuntimeError(f"{engine} startup timeout")
                    original = "こんにちは。お元気ですか？"
                    if engine == "renpy":
                        middle = translate(port, original, "ja", "en")
                        result = translate(port, middle, "en", "pb")
                    else:
                        result = translate(port, original, "ja", "pb")
                    print(f"PASS {engine}: {original} -> {result}", flush=True)
                    if engine == "unity":
                        config.update(source_language="en", flow_mode="direct", intermediate_language=None)
                        (state / "unity_uat_config.json").write_text(json.dumps(config))
                        direct = translate(port, "Hello, how are you?", "en", "pb")
                        print(f"PASS unity direct: {direct}", flush=True)
                except Exception:
                    log.seek(0)
                    print(log.read(), flush=True)
                    raise
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
