import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path=BASE_DIR / ".env"):
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}, 请在 .env 中配置")
    return value


load_env_file()

BASE_URL = os.getenv("WHALE_BASE_URL", "http://localhost:8001")
USERNAME = require_env("WHALE_USERNAME")
PASSWORD = require_env("WHALE_PASSWORD")