"""Root-conftest logging setup; importing fixture helpers does not run live I/O."""
import logging
from pathlib import Path

cleanup_log = logging.getLogger("whale.cleanup")


def configure_http_logging():
    log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(exist_ok=True)
    http_log = logging.getLogger("whale.http")
    if not http_log.handlers:
        handler = logging.FileHandler(log_dir / "http.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        http_log.addHandler(handler)
        http_log.setLevel(logging.INFO)
        http_log.propagate = False
