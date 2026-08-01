import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, skip_if_pending

_d = load_yaml("data/system.yaml")
health_success = _d["health_success"]
metrics_success = _d["metrics_success"]


def _ids(cases):
    return [c["case_id"] for c in cases]


@allure.feature("系统")
@allure.story("健康检查")
class TestHealth:

    @pytest.mark.smoke
    @pytest.mark.parametrize("case", health_success, ids=_ids(health_success))
    def test_health_ok(self, case, client):
        """/health 无鉴权 → 200 {"status":"ok"}。"""
        skip_if_pending(case)
        resp = client.get("/health")
        assert_response(resp, case["expected"])
        assert resp.json()["status"] == "ok", f"health status 应为 ok: {resp.text}"


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
