import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, assert_values, skip_if_pending

_d = load_yaml("data/schedule.yaml")
create_success = _d["create_success"]
list_success = _d["list_success"]
detail_success = _d["detail_success"]
detail_fail = _d["detail_fail"]
update_success = _d["update_success"]
delete_success = _d["delete_success"]
create_no_token = _d["create_no_token"]


def _ids(cases):
    return [c["case_id"] for c in cases]


def _create(project_client, unique_name, prefix, cron):
    resp = project_client.post("/schedules", json={
        "name": unique_name(prefix), "cron": cron,
    })
    assert resp.status_code == 201, f"前置建定时任务应成功: {resp.text}"
    return resp.json()["id"]


@allure.feature("定时任务")
@allure.story("创建定时任务")
class TestCreateSchedule:

    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        resp = project_client.post("/schedules", json={
            "name": name, "cron": req["cron"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "cron": req["cron"]})
        api_cleanup(f"/schedules/{resp.json()['id']}")

    @pytest.mark.parametrize("case", create_no_token, ids=_ids(create_no_token))
    def test_create_without_token(self, case, project_only_client, unique_name, api_cleanup):
        """特征化：schedule 创建无鉴权，不带 token 也能建(201)——被测系统鉴权缺口。"""
        skip_if_pending(case)
        req = case["request"]
        resp = project_only_client.post("/schedules", json={
            "name": unique_name(req["name_prefix"]), "cron": req["cron"],
        })
        assert_response(resp, case["expected"])
        if resp.status_code < 300:
            api_cleanup(f"/schedules/{resp.json()['id']}")


@allure.feature("定时任务")
@allure.story("定时任务列表")
class TestListSchedule:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/schedules")
        assert_response(resp, case["expected"])


@allure.feature("定时任务")
@allure.story("定时任务详情")
class TestGetScheduleDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        sid = _create(project_client, unique_name, "auto_sch_get_", "* * * * *")
        api_cleanup(f"/schedules/{sid}")
        resp = project_client.get(f"/schedules/{sid}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/schedules/{case['request']['schedule_id']}")
        assert_response(resp, case["expected"])


@allure.feature("定时任务")
@allure.story("更新定时任务")
class TestUpdateSchedule:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        sid = _create(project_client, unique_name, "auto_sch_pre_", "* * * * *")
        api_cleanup(f"/schedules/{sid}")
        req = case["request"]
        name = unique_name(req["name_prefix"])
        resp = project_client.put(f"/schedules/{sid}", json={
            "name": name, "cron": req["cron"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "cron": req["cron"]})
        again = project_client.get(f"/schedules/{sid}")
        assert_values(again, {"name": name, "cron": req["cron"]})


@allure.feature("定时任务")
@allure.story("删除定时任务")
class TestDeleteSchedule:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, project_client, unique_name):
        skip_if_pending(case)
        sid = _create(project_client, unique_name, "auto_sch_del_", "* * * * *")
        resp = project_client.delete(f"/schedules/{sid}")
        assert_response(resp, case["expected"])
        again = project_client.get(f"/schedules/{sid}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"
