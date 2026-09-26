"""Structured logging setup: rotating file handler + console handler.

Call ``configure_logging()`` once at process start. Every module then just
does ``logging.getLogger("voiceflow.<module>")`` and inherits this config.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading

from voiceflow.paths import LOG_PATH, ensure_directories

_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)-24s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False
_configure_lock = threading.Lock()


def configure_logging(level: int = logging.INFO, console: bool = True) -> None:
    global _configured
    with _configure_lock:
        if _configured:
            return
        ensure_directories()

        root = logging.getLogger("voiceflow")
        root.setLevel(level)
        root.propagate = False

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        file_handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)

        sys.excepthook = _make_excepthook(root)
        threading.excepthook = _make_thread_excepthook(root)

        _configured = True
        root.info("=" * 70)
        root.info("VoiceFlow logging initialized -> %s", LOG_PATH)


def _make_excepthook(logger: logging.Logger):
    def _hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Uncaught exception on main thread", exc_info=(exc_type, exc_value, exc_traceback)
        )

    return _hook


def _make_thread_excepthook(logger: logging.Logger):
    def _hook(args: threading.ExceptHookArgs):
        logger.critical(
            "Uncaught exception on thread %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    return _hook
