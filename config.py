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

# 用例执行引擎在被测容器内部发起请求,访问被测服务自身要用容器内地址(8000),
# 而不是宿主映射端口(8001)。给 case/scenario 执行用例的环境 base_url 用这个。
RUNNER_BASE_URL = os.getenv("WHALE_RUNNER_BASE_URL", "http://localhost:8000")