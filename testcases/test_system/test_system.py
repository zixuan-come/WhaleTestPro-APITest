import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, skip_if_pending

_d = load_yaml("data/system.yaml")
live_success = _d["live_success"]
ready_success = _d["ready_success"]
metrics_success = _d["metrics_success"]


def _ids(cases):
    return [c["case_id"] for c in cases]


@allure.feature("系统")
@allure.story("健康检查")
class TestHealth:

    @pytest.mark.smoke
    @pytest.mark.parametrize("case", live_success, ids=_ids(live_success))
    def test_health_live(self, case, client):
        """/health/live 只检查后端进程存活，不依赖数据库。"""
        skip_if_pending(case)
        resp = client.get("/health/live")
        assert_response(resp, case["expected"])
        assert resp.json()["status"] == "alive", f"live status 应为 alive: {resp.text}"

    @pytest.mark.parametrize("case", ready_success, ids=_ids(ready_success))
    def test_health_ready(self, case, client):
        """/health/ready 同时检查主库和影子库是否可用。"""
        skip_if_pending(case)
        resp = client.get("/health/ready")
        assert_response(resp, case["expected"])
        body = resp.json()
        assert body == {
            "status": "ready",
            "main_database": "ok",
            "shadow_database": "ok",
        }, f"ready 应确认主库和影子库均可用: {resp.text}"


@allure.feature("系统")
@allure.story("Prometheus 指标")
class TestMetrics:

    @pytest.mark.parametrize("case", metrics_success, ids=_ids(metrics_success))
    def test_metrics_ok(self, case, client):
        """/metrics → 200 prometheus 文本(text/plain,含 # HELP)。"""
        skip_if_pending(case)
        resp = client.get("/metrics")
        assert_response(resp, case["expected"])
        assert "text/plain" in resp.headers.get("content-type", ""), \
            f"metrics content-type 应为 text/plain: {resp.headers.get('content-type')}"
        assert "# HELP" in resp.text, f"metrics 应为 prometheus 文本: {resp.text[:80]}"
