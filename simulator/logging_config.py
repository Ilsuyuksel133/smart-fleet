import json
import logging
import os
from datetime import datetime, timezone

# LogRecord'un kendi alanları; bunların dışındaki her şey "extra" ile gelen ek alandır.
# color_message: uvicorn'un terminal renk kodlu kopyası, JSON'da gereksiz.
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",
}


class JsonFormatter(logging.Formatter):
    """Her log kaydını tek satırlık bir JSON objesine çevirir."""

    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    # Uvicorn'un kendi düz metin handler'larını kaldır, loglar root'tan JSON olarak çıksın
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
