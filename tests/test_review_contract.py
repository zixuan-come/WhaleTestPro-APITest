"""Deterministic regressions for payload and cleanup, no live platform."""
from types import SimpleNamespace

import pytest


class Reply:
    def __init__(self, status, data=None):
        self.status_code, self.data = status, data
        self.text = "isolated response"
    def json(self):
        return self.data


def test_schedule_not_found_payload_contains_current_environment():
    from testcases.test_contract.test_negative_contract import TestNegativeContract, resources
    schedule = next(row for row in resources if row["name"] == "schedule")
    calls = []
    def put(url, json):
        calls.append(json)
        return Reply(404 if json.get("env_id") == 123 else 422)
    TestNegativeContract().test_update_not_found(schedule, SimpleNamespace(put=put), 123)
    assert calls[0]["env_id"] == 123
    assert "env_id" not in schedule["update_body"], "不要原地污染参数化用例数据"
