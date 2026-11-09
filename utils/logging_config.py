import logging
import re
from logging.handlers import RotatingFileHandler

from config.settings import settings
from utils.pii_masker import mask_text_pii

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*([A-Za-z0-9._%+-])@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_configured = False


class PIIMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if settings.MASK_PII_IN_LOGS:
            msg = mask_text_pii(record.getMessage())
            record.msg, record.args = _EMAIL.sub(r"\1***\2@\3", msg), None
        return True


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(settings.APP_LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    console = logging.StreamHandler()
    root = logging.getLogger()
    root.setLevel(level)
    for h in (file_handler, console):
        h.setFormatter(fmt)
        h.addFilter(PIIMaskingFilter())
        root.addHandler(h)
    for noisy in ("httpx", "httpcore", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True
