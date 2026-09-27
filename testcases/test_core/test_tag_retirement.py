"""Removed labels must not silently become empty or all-case execution."""
import pytest
from common.core_flow import business

pytestmark = pytest.mark.core_flow


@pytest.mark.parametrize("resource", ["case", "suite", "schedule"])
def test_removed_tag_fields_are_rejected(core_workspace, resource):
    w = core_workspace
    if resource == "case":
        path, payload = "/cases", {"name": w.name(), "interface_id": w.interface()["id"], "expected_status": 200, "tags": ["smoke"]}
    elif resource == "suite":
        path, payload = "/suites", {"name": w.name(), "type": "mixed", "tags": ["smoke"]}
    else:
        path, payload = "/schedules", {"name": w.name(), "cron": "0 2 * * *", "env_id": w.environment()["id"], "tag": "smoke"}
    business(w.client.post(path, json=payload), 422)
    assert business(w.client.get("/suites")) == []
    assert business(w.client.get("/schedules")) == []
    assert w.reports()["total"] == 0
