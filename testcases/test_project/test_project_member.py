import allure
import pytest

from common.assert_util import assert_response, assert_values
from common.yaml_util import load_yaml

list_success = load_yaml("data/project/list_project_members.yaml")["list_project_members_success"]
list_fail = load_yaml("data/project/list_project_members.yaml")["list_project_members_fail"]
add_success = load_yaml("data/project/add_project_member.yaml")["add_project_member_success"]
add_fail = load_yaml("data/project/add_project_member.yaml")["add_project_member_fail"]
update_success = load_yaml("data/project/update_project_member_role.yaml")["update_project_member_role_success"]
update_fail = load_yaml("data/project/update_project_member_role.yaml")["update_project_member_role_fail"]
remove_success = load_yaml("data/project/remove_project_member.yaml")["remove_project_member_success"]
remove_fail = load_yaml("data/project/remove_project_member.yaml")["remove_project_member_fail"]
search_success = load_yaml("data/project/search_project_member_candidates.yaml")["search_project_member_candidates_success"]
search_fail = load_yaml("data/project/search_project_member_candidates.yaml")["search_project_member_candidates_fail"]


def _ids(cases):
    return [case["case_id"] for case in cases]


def _client(context, actor, anonymous_client):
    return anonymous_client if actor == "anonymous" else context["clients"][actor]


def _member_body(response):
    body = response.json()
    assert isinstance(body, dict), f"成员响应应该是 dict: {response.text}"
    assert isinstance(body.get("user"), dict), f"成员响应缺少 user 对象: {response.text}"
    return body


@allure.feature("项目成员管理")
@allure.story("查看项目成员")
class TestListProjectMembers:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, member_project_context, client):
        target = _client(member_project_context, case["actor"], client)
        response = target.get(
            f"/projects/{member_project_context['project_id']}/members"
        )
        assert_response(response, case["expected"])
        rows = response.json()
        assert {row["user_id"] for row in rows} >= {
            member_project_context["users"]["admin"]["id"],
            member_project_context["users"]["member"]["id"],
        }

    @pytest.mark.parametrize("case", list_fail, ids=_ids(list_fail))
    def test_list_fail(self, case, member_project_context, client):
        target = _client(member_project_context, case["actor"], client)
        response = target.get(
            f"/projects/{member_project_context['project_id']}/members"
        )
        assert_response(response, case["expected"])


@allure.feature("项目成员管理")
@allure.story("新增项目成员")
class TestAddProjectMember:

    @pytest.mark.parametrize("case", add_success, ids=_ids(add_success))
    def test_add_success(self, case, member_project_context):
        context = member_project_context
        target = context["clients"][case["actor"]]
        target_user_id = context["users"]["outsider"]["id"]
        response = target.post(
            f"/projects/{context['project_id']}/members",
            json={"user_id": target_user_id, "role": case["request"]["role"]},
        )
        assert_response(response, case["expected"])
        body = _member_body(response)
        assert_values(response, {"user_id": target_user_id, "role": "member"})
        assert body["user"]["id"] == target_user_id

    @pytest.mark.parametrize("case", add_fail, ids=_ids(add_fail))
    def test_add_fail(self, case, member_project_context, client):
        context = member_project_context
        target = _client(context, case["actor"], client)
        request = case.get("request", {})
        if case["case_id"] == "duplicate_project_member":
            user_id = context["users"]["member"]["id"]
        else:
            user_id = request.get("user_id", context["users"]["outsider"]["id"])

        response = target.post(
            f"/projects/{context['project_id']}/members",
            json={"user_id": user_id, "role": request.get("role", "member")},
        )
        assert_response(response, case["expected"])


@allure.feature("项目成员管理")
@allure.story("修改成员角色")
class TestUpdateProjectMemberRole:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, member_project_context):
        context = member_project_context
        target = context["clients"][case["actor"]]
        member_id = context["member_id"]("member")
        response = target.patch(
            f"/projects/{context['project_id']}/members/{member_id}",
            json={"role": case["request"]["role"]},
        )
        assert_response(response, case["expected"])
        assert_values(response, {"id": member_id, "role": "admin"})

    @pytest.mark.parametrize("case", update_fail, ids=_ids(update_fail))
    def test_update_fail(self, case, member_project_context, client):
        context = member_project_context
        target = _client(context, case["actor"], client)
        request = case.get("request", {})
        if case["case_id"] == "update_project_owner_role":
            member_id = context["member_id"]("owner")
        elif case["case_id"] == "cross_project_update_member":
            member_id = context["make_other_project"]()["member_id"]
        else:
            member_id = request.get("member_id", context["member_id"]("member"))

        response = target.patch(
            f"/projects/{context['project_id']}/members/{member_id}",
            json={"role": request.get("role", "admin")},
        )
        assert_response(response, case["expected"])


@allure.feature("项目成员管理")
@allure.story("移除项目成员")
class TestRemoveProjectMember:

    @pytest.mark.parametrize("case", remove_success, ids=_ids(remove_success))
    def test_remove_success(self, case, member_project_context):
        context = member_project_context
        target = context["clients"][case["actor"]]
        member_id = context["member_id"]("member")
        response = target.delete(
            f"/projects/{context['project_id']}/members/{member_id}"
        )
        assert_response(response, case["expected"])

        again = context["clients"]["owner"].get(
            f"/projects/{context['project_id']}/members"
        )
        assert again.status_code == 200
        assert all(row["id"] != member_id for row in again.json())

    @pytest.mark.parametrize("case", remove_fail, ids=_ids(remove_fail))
    def test_remove_fail(self, case, member_project_context, client):
        context = member_project_context
        target = _client(context, case["actor"], client)
        request = case.get("request", {})
        if case["case_id"] == "remove_project_owner":
            member_id = context["member_id"]("owner")
        elif case["case_id"] == "cross_project_remove_member":
            member_id = context["make_other_project"]()["member_id"]
        else:
            member_id = request.get("member_id", context["member_id"]("member"))

        response = target.delete(
            f"/projects/{context['project_id']}/members/{member_id}"
        )
        assert_response(response, case["expected"])


@allure.feature("项目成员管理")
@allure.story("候选成员搜索")
class TestSearchProjectMemberCandidates:

    @pytest.mark.parametrize("case", search_success, ids=_ids(search_success))
    def test_search_success(self, case, member_project_context):
        context = member_project_context
        target = context["clients"][case["actor"]]
        keyword = context["users"]["outsider"]["username"]
        response = target.get(
            f"/projects/{context['project_id']}/member-candidates",
            params={"keyword": keyword, "limit": 20},
        )
        assert_response(response, case["expected"])
        assert context["users"]["outsider"]["id"] in {
            item["id"] for item in response.json()
        }
        assert context["users"]["member"]["id"] not in {
            item["id"] for item in response.json()
        }

    @pytest.mark.parametrize("case", search_fail, ids=_ids(search_fail))
    def test_search_fail(self, case, member_project_context, client):
        context = member_project_context
        target = _client(context, case["actor"], client)
        keyword = case.get("request", {}).get(
            "keyword",
            context["users"]["outsider"]["username"],
        )
        response = target.get(
            f"/projects/{context['project_id']}/member-candidates",
            params={"keyword": keyword},
        )
        assert_response(response, case["expected"])
