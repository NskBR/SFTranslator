# -*- coding: utf-8 -*-
import sys
import os
import threading
import time
from datetime import datetime

class UATLogger:
    """
    Logger que打印 no console (cmd) e opcionalmente em arquivo.
    Usa lock pra nao misturar linhas.
    """
    _lock = threading.Lock()
    _log_file = None

    @classmethod
    def init(cls, log_path=None, show_console=True):
        cls._show_console = show_console
        cls._console = None
        if log_path:
            try:
                log_dir = os.path.dirname(log_path)
                if log_dir and not os.path.isdir(log_dir):
                    os.makedirs(log_dir)
            except Exception:
                pass
            try:
                cls._log_file = open(log_path, "a", encoding="utf-8")
            except TypeError:
                cls._log_file = open(log_path, "a")
            except Exception:
                cls._log_file = None

    @classmethod
    def reopen_console(cls):
        """Reabre o handle do console apos o AllocConsole() do phase1."""
        if not getattr(cls, "_show_console", True):
            return
        try:
            if cls._console:
                try:
                    cls._console.close()
                except Exception:
                    pass
            try:
                cls._console = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            except TypeError:
                cls._console = open("CONOUT$", "w", buffering=1)
        except Exception:
            cls._console = None

    @classmethod
    def _write(cls, level, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = "[{}] [{}] {}".format(ts, level, msg)
        with cls._lock:
            if getattr(cls, "_show_console", True):
                try:
                    if cls._console:
                        cls._console.write(line + "\n")
                        cls._console.flush()
                    else:
                        sys.stdout.write(line + "\n")
                        sys.stdout.flush()
                except Exception:
                    pass
            if cls._log_file:
                try:
                    cls._log_file.write(line + "\n")
                    cls._log_file.flush()
                except Exception:
                    pass

    @classmethod
    def info(cls, msg): cls._write("INFO", msg)
    @classmethod
    def ok(cls, msg): cls._write(" OK ", msg)
    @classmethod
    def warn(cls, msg): cls._write("WARN", msg)
    @classmethod
    def error(cls, msg): cls._write("ERRO", msg)
    @classmethod
    def api(cls, msg): cls._write(" API", msg)
    @classmethod
    def cache(cls, msg): cls._write("CACH", msg)
    @classmethod
    def hook(cls, msg): cls._write("HOOK", msg)
