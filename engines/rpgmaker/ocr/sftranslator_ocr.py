"""Experimental window OCR for RPG Maker versions without a JavaScript plugin API.

This process observes only the launched game's window. It never changes game files.
"""

import asyncio
import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import urllib.request

from PIL import ImageGrab
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage import StorageFile
from winrt.windows.globalization import Language


user32 = ctypes.windll.user32
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]


def game_window(pid):
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            rect = wintypes.RECT()
            origin = wintypes.POINT(0, 0)
            if user32.GetClientRect(hwnd, ctypes.byref(rect)) and user32.ClientToScreen(hwnd, ctypes.byref(origin)):
                width, height = rect.right, rect.bottom
                if width >= 160 and height >= 100:
                    found.append((width * height, hwnd, (origin.x, origin.y, width, height)))
        return True

    user32.EnumWindows(collect, 0)
    return max(found, default=None)


async def recognize(path, engine):
    file = await StorageFile.get_file_from_path_async(str(path))
    stream = await file.open_read_async()
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        bounds = [word.bounding_rect for word in line.words]
        if not bounds:
            continue
        x, y = min(rect.x for rect in bounds), min(rect.y for rect in bounds)
        right = max(rect.x + rect.width for rect in bounds)
        bottom = max(rect.y + rect.height for rect in bounds)
        lines.append((line.text.strip(), SimpleNamespace(x=x, y=y, width=right-x, height=bottom-y)))
    return lines


def translatable(text):
    return len(text) >= 3 and sum(char.isalpha() for char in text) >= 3 and not re.fullmatch(r"[\d\s\W]+", text)


def translate(text, port, source, target):
    body = json.dumps({"q": text, "source": source, "target": target}).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{port}/translate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=40) as response:
        value = json.load(response).get("translatedText", text)
    return value if isinstance(value, str) and value.strip() else text


def main(pid, port, source, target):
    languages = [language.language_tag for language in OcrEngine.available_recognizer_languages]
    print(f"[OCR] Idiomas Windows disponíveis: {', '.join(languages) or 'nenhum'}", flush=True)
    source_tag = {"pb": "pt-BR", "en": "en-US", "ja": "ja-JP", "zh": "zh-Hans", "ko": "ko-KR"}.get(source, source)
    matching = next((tag for tag in languages if tag.lower().split('-')[0] == source_tag.lower().split('-')[0]), None)
    engine = OcrEngine.try_create_from_language(Language(matching)) if matching else OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        print("[OCR] Nenhum idioma OCR instalado no Windows. Instale o recurso de reconhecimento do idioma de origem.", flush=True)
        return 2
    if not matching:
        print(f"[OCR] Aviso: idioma de origem {source_tag} não tem pacote OCR instalado; reconhecimento pelo idioma {engine.recognizer_language.language_tag} pode falhar.", flush=True)
    print(f"[OCR] Reconhecedor ativo: {engine.recognizer_language.language_tag}", flush=True)

    cache_file = Path(os.environ["UAT_OCR_CACHE"])
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    cache_lock = threading.Lock()
    pending = set()
    retry_after = {}
    lines = []
    geometry = None
    active = True
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="sfocr")

    def translate_one(text):
        try:
            result = translate(text, port, source, target)
            with cache_lock:
                cache[text] = result
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            if result != text:
                print(f"[OCR] {text[:100]} => {result[:100]}", flush=True)
        except Exception as error:
            with cache_lock:
                retry_after[text] = time.monotonic() + 5
            print(f"[OCR] Falha ao traduzir {text[:60]!r}: {error}", flush=True)
        finally:
            with cache_lock:
                pending.discard(text)

    def worker():
        nonlocal lines, geometry, active
        screenshot = Path(os.environ["UAT_OCR_CAPTURE"])
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        while active:
            window = game_window(pid)
            if not window:
                geometry = None
                time.sleep(0.8)
                continue
            _, hwnd, rect = window
            geometry = rect
            try:
                image = ImageGrab.grab(window=hwnd)
                image.save(screenshot)
                detected = asyncio.run(recognize(screenshot, engine))
                lines = [(text, bounds) for text, bounds in detected if translatable(text)]
                with cache_lock:
                    for text, _ in lines:
                        if text not in cache and text not in pending and time.monotonic() >= retry_after.get(text, 0):
                            pending.add(text)
                            pool.submit(translate_one, text)
            except Exception as error:
                print(f"[OCR] Captura falhou: {error}", flush=True)
                lines = []
            time.sleep(1.0)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.wm_attributes("-transparentcolor", "#010203")
    root.configure(bg="#010203")
    canvas = tk.Canvas(root, bg="#010203", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    root.update_idletasks()
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    style = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, style | 0x20 | 0x80000 | 0x08000000 | 0x80)  # click-through, layered, no activate
    root.withdraw()
    threading.Thread(target=worker, daemon=True).start()

    def refresh():
        canvas.delete("all")
        if geometry:
            x, y, width, height = geometry
            root.geometry(f"{width}x{height}{x:+d}{y:+d}")
            window = game_window(pid)
            if window and user32.GetForegroundWindow() == window[1]:
                root.deiconify()
            else:
                root.withdraw()
            with cache_lock:
                visible = [(text, bounds, cache.get(text)) for text, bounds in lines]
            for original, bounds, translated in visible:
                if not translated or translated == original:
                    continue
                left, top = int(bounds.x), int(bounds.y)
                line_height = max(18, int(bounds.height))
                area_width = max(120, min(width - left, int(bounds.width * 1.65)))
                if area_width <= 0:
                    continue
                text_id = canvas.create_text(left + 2, top, text=translated, fill="white", anchor="nw", width=area_width - 5,
                                             font=("Arial", max(12, min(25, int(line_height * .75)))))
                text_bounds = canvas.bbox(text_id)
                bottom = max(top + line_height + 3, (text_bounds[3] + 3) if text_bounds else top + line_height + 3)
                background = canvas.create_rectangle(left - 2, top - 2, left + area_width, bottom, fill="#131820", outline="#131820")
                canvas.tag_lower(background, text_id)
        else:
            root.withdraw()
        root.after(250, refresh)

    root.after(250, refresh)
    try:
        root.mainloop()
    finally:
        active = False
        pool.shutdown(wait=False, cancel_futures=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]))
