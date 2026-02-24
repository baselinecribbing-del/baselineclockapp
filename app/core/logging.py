import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include structured "extra" fields passed to logger.*(..., extra={...})
        standard = {
            "name","msg","args","levelname","levelno","pathname","filename","module",
            "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
            "relativeCreated","thread","threadName","processName","process",
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in standard}
        if extras:
            payload["extra"] = extras

        # Include exception traceback for logger.exception(...)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack_info"] = record.stack_info

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(message)s",
    )

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(JsonFormatter())
