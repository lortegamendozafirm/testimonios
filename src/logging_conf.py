# src/logging_config.py
import json
import logging
import os
import sys
from typing import Optional, Dict, Any

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    """
    Formateador JSON line-delimited para logs estructurados.
    Respeta fields estándar (level, name, message) y mezcla 'extra'.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }

        # 'extra' se incrusta en record.__dict__ por logging; filtramos claves conocidas
        # y adjuntamos las que parezcan contextuales.
        reserved = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "asctime"
        }

        for k, v in record.__dict__.items():
            if k not in reserved and not k.startswith("_"):
                payload[k] = v

        # Adjunta rastro de excepción si existe
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def _mask_pii_in_message(msg: str) -> str:
    """
    Si quisieras en el futuro, aquí puedes aplicar masking adicional.
    Por ahora devolvemos tal cual; el control viene por LOG_INCLUDE_PII.
    """
    return msg


def configure_logging(level_name: str = "INFO", fmt: str = "json", include_pii: bool = False) -> None:
    """
    Idempotente. Configura logging en texto o JSON.
    - Llama esto lo más temprano posible (ej. en main.py).
    - include_pii=False (recomendado). Si True, no se filtra contenido.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = _LEVELS.get(level_name.upper(), logging.INFO)
    root = logging.getLogger()

    # Si Uvicorn ya añadió handlers, los respetamos pero alineamos niveles
    if not root.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        if fmt.lower() == "json":
            handler.setFormatter(_JsonFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            ))
        root.addHandler(handler)

    root.setLevel(level)

    # Silenciar librerías ruidosas
    for noisy in (
        "googleapiclient.discovery",
        "googleapiclient.discovery_cache",
        "google.auth.transport.requests",
        "urllib3",
        "httpx",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Alinear Uvicorn con el nivel elegido
    for uv in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(uv).setLevel(level)

    # Hook opcional para PII (hoy sin cambios; deja el switch para el futuro)
    if not include_pii:
        # Puedes insertar filtros aquí si quisieras redactar mensajes
        pass

    _CONFIGURED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name if name else __name__)


def bootstrap_logging_from_env() -> None:
    """
    Conveniencia: si prefieres no pasar parámetros manualmente.
    Usa LOG_LEVEL, LOG_FORMAT y LOG_INCLUDE_PII del entorno.
    """
    level = os.getenv("LOG_LEVEL", "INFO")
    fmt = os.getenv("LOG_FORMAT", "json")
    include_pii = os.getenv("LOG_INCLUDE_PII", "false").lower() in {"true", "1", "yes"}
    configure_logging(level_name=level, fmt=fmt, include_pii=include_pii)
