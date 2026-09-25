"""Offline tests must fail immediately if any live setup escapes isolation."""
import pytest
import httpx
import requests
import subprocess
import platform
import redis

# Windows metadata discovery may invoke `ver`; cache it before the I/O guard.
platform.uname()


@pytest.fixture(autouse=True)
def forbid_live_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("离线测试禁止真实 HTTP 请求或外部进程")
    monkeypatch.setattr(httpx, "request", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(redis.Redis, "execute_command", forbidden)
