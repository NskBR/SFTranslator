"""Stage a pinned UE4SS observer inside the installer; no runtime download."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile
import json


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src-tauri/resources/runtimes/unreal"
SOURCE = ROOT / "engines/unreal/observer.lua"
ARCHIVE = ROOT / "src-tauri/target/unreal-probe/UE4SS_v3.0.1-1147-g919ffaca.zip"
URL = (
    "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/"
    "experimental-latest/UE4SS_v3.0.1-1147-g919ffaca.zip"
)
SHA256 = "35ca2531964b7d83d6f1bd2bba184d61f74eb39bc6ddcdcbfc128e5dcb80e0ad"


def stage() -> None:
    if ARCHIVE.is_file():
        payload = ARCHIVE.read_bytes()
    else:
        request = Request(URL, headers={"User-Agent": "SFTranslator-build"})
        with urlopen(request, timeout=90) as response:
            payload = response.read()
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE.write_bytes(payload)
    digest = sha256(payload).hexdigest()
    if digest != SHA256:
        raise RuntimeError(f"UE4SS archive SHA-256 mismatch: {digest}")

    DEST.mkdir(parents=True, exist_ok=True)
    with ZipFile(BytesIO(payload)) as archive:
        for member, destination in {
            "dwmapi.dll": "dwmapi.dll",
            "ue4ss/UE4SS.dll": "ue4ss/UE4SS.dll",
            "ue4ss/UE4SS-settings.ini": "ue4ss/UE4SS-settings.ini",
            "ue4ss/LICENSE": "ue4ss/LICENSE",
        }.items():
            path = DEST / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(member))
    observer = DEST / "ue4ss/Mods/SFTranslatorObserver/Scripts/main.lua"
    observer.parent.mkdir(parents=True, exist_ok=True)
    observer.write_bytes(SOURCE.read_bytes())
    (DEST / "ue4ss/Mods/mods.txt").write_text("SFTranslatorObserver : 1\n", encoding="utf-8")
    (DEST / "ue4ss/Mods/mods.json").write_text(json.dumps([
        {"mod_name": "SFTranslatorObserver", "mod_enabled": True}
    ]), encoding="utf-8")
    manifest_path = DEST.parent / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["engines"] = list(dict.fromkeys([*manifest.get("engines", []), "unreal-observer"]))
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    print("UE4SS experimental staged with SHA-256 verified; only SFTranslatorObserver enabled.")


if __name__ == "__main__":
    stage()
