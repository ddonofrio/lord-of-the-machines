from __future__ import annotations

import atexit
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lord_of_the_machines.runtime.paths import LOG_DIR


DEFAULT_LOG_DIR = LOG_DIR
LOGGER_ROOT = "lord_of_the_machines"
_CURRENT_LOG_PATH: Path | None = None

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "openai_api_key",
    "password",
    "secret",
    "token",
    "x-api-key",
}


def configure_run_logging(
    *,
    run_name: str = "run",
    log_dir: str | Path | None = None,
    level: int = logging.DEBUG,
) -> Path:
    global _CURRENT_LOG_PATH

    resolved_log_dir = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    resolved_log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in run_name)
    log_path = resolved_log_dir / f"{safe_name}-{timestamp}.log"

    root_logger = logging.getLogger(LOGGER_ROOT)
    _close_handlers(root_logger)
    root_logger.setLevel(level)
    root_logger.propagate = False

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(handler)

    _CURRENT_LOG_PATH = log_path
    root_logger.debug("logging configured: %s", log_path)
    return log_path


def close_run_logging() -> None:
    _close_handlers(logging.getLogger(LOGGER_ROOT))


def current_log_path() -> Path | None:
    return _CURRENT_LOG_PATH


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_ROOT}.{name}")


def log_json(logger: logging.Logger, label: str, value: Any, *, level: int = logging.DEBUG) -> None:
    if not logger.isEnabledFor(level):
        return
    logger.log(level, "%s\n%s", label, json.dumps(to_loggable(value), ensure_ascii=False, indent=2))


def to_loggable(value: Any) -> Any:
    return _redact(_make_json_safe(value))


def _make_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return _make_json_safe(asdict(value))

    output_text = getattr(value, "output_text", None)
    response_id = getattr(value, "id", None)
    status = getattr(value, "status", None)
    usage = getattr(value, "usage", None)
    if output_text is not None or response_id is not None or status is not None or usage is not None:
        return {
            "type": type(value).__name__,
            "id": response_id,
            "status": status,
            "usage": _make_json_safe(usage),
            "output_text": output_text,
        }

    return repr(value)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _close_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.flush()
        handler.close()


atexit.register(close_run_logging)
