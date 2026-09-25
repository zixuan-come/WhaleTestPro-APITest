"""Safety regressions using synthetic .env and fixture transports only."""
from pathlib import Path
import pytest
from packaging.requirements import Requirement
import config


def test_offline_guard_redis_dependency_is_declared():
    # Marker selection still imports tests/conftest.py during collection.
    root = Path(__file__).resolve().parents[1]
    lines = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    names = {Requirement(line.split("#", 1)[0].strip()).name.lower()
             for line in lines if line.split("#", 1)[0].strip()}
    assert "redis" in names, "Redis I/O guard must not rely on backend-only dependencies"


@pytest.mark.parametrize("key,value", [
    ("WHALE_PERF_ALLOW_LOAD", "0"), ("WHALE_PERF_CORE_ALLOW_WRITES", "0"),
    ("WHALE_CORE_ALLOW_WRITES", "0"),
    ("WHALE_BASE_URL", "http://isolated.invalid"),
    ("WHALE_PERF_BASE_URL", "http://fixture.invalid"),
    ("WHALE_RUNNER_BASE_URL", "http://runner.invalid"),
    ("WHALE_PERF_FIXTURE_BASE_URL", "http://fixture.invalid"),
])
def test_process_environment_wins_over_env_file(monkeypatch, tmp_path, key, value):
    monkeypatch.setenv(key, value)
    env = tmp_path / "synthetic.env"
    env.write_text(f"{key}=1\n", encoding="utf-8")
    config.load_env_file(env)
    assert config.os.environ[key] == value


def test_env_file_still_supplies_unset_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("WHALE_REVIEW_SYNTHETIC", raising=False)
    env = tmp_path / "synthetic.env"
    env.write_text("WHALE_REVIEW_SYNTHETIC='default'\n", encoding="utf-8")
    config.load_env_file(env)
    assert config.os.environ["WHALE_REVIEW_SYNTHETIC"] == "default"
    monkeypatch.delenv("WHALE_REVIEW_SYNTHETIC")
