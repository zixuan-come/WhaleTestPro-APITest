import allure
import pytest

from common.assert_util import assert_response, assert_values
from common.yaml_util import load_yaml


list_success = load_yaml("data/team/list_team_members.yaml")["list_team_members_success"]
list_fail = load_yaml("data/team/list_team_members.yaml")["list_team_members_fail"]
add_success = load_yaml("data/team/add_team_member.yaml")["add_team_member_success"]
add_fail = load_yaml("data/team/add_team_member.yaml")["add_team_member_fail"]
update_success = load_yaml("data/team/update_team_member_role.yaml")["update_team_member_role_success"]
update_fail = load_yaml("data/team/update_team_member_role.yaml")["update_team_member_role_fail"]
remove_success = load_yaml("data/team/remove_team_member.yaml")["remove_team_member_success"]
remove_fail = load_yaml("data/team/remove_team_member.yaml")["remove_team_member_fail"]
search_success = load_yaml("data/team/search_team_member_candidates.yaml")["search_team_member_candidates_success"]
search_fail = load_yaml("data/team/search_team_member_candidates.yaml")["search_team_member_candidates_fail"]


def _ids(cases):
    return [case["case_id"] for case in cases]


def _client(context, actor, anonymous_client):
    return anonymous_client if actor == "anonymous" else context["clients"][actor]


def _member_body(response):
    body = response.json()
    assert isinstance(body, dict), f"成员响应应该是 dict: {response.text}"
    assert isinstance(body.get("user"), dict), f"成员响应缺少 user 对象: {response.text}"
    return body


@allure.feature("团队成员管理")
@allure.story("查看团队成员")
class TestListTeamMembers:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, team_member_context, client):
        target = _client(team_member_context, case["actor"], client)
        response = target.get(f"/teams/{team_member_context['team_id']}/members")
        assert_response(response, case["expected"])
        rows = response.json()
        assert {row["user_id"] for row in rows} >= {
            team_member_context["users"]["admin"]["id"],
            team_member_context["users"]["member"]["id"],
        }

    @pytest.mark.parametrize("case", list_fail, ids=_ids(list_fail))
    def test_list_fail(self, case, team_member_context, client):
        target = _client(team_member_context, case["actor"], client)
        response = target.get(f"/teams/{team_member_context['team_id']}/members")
        assert_response(response, case["expected"])


@allure.feature("团队成员管理")
@allure.story("新增团队成员")
class TestAddTeamMember:

    @pytest.mark.parametrize("case", add_success, ids=_ids(add_success))
    def test_add_success(self, case, team_member_context):
        context = team_member_context
        target = context["clients"][case["actor"]]
        target_user_id = context["users"]["outsider"]["id"]
        response = target.post(
            f"/teams/{context['team_id']}/members",
            json={"user_id": target_user_id, "role": case["request"]["role"]},
        )
        assert_response(response, case["expected"])
        body = _member_body(response)
        assert_values(response, {"user_id": target_user_id, "role": "member"})
        assert body["user"]["id"] == target_user_id

    @pytest.mark.parametrize("case", add_fail, ids=_ids(add_fail))
    def test_add_fail(self, case, team_member_context, client):
        context = team_member_context
        target = _client(context, case["actor"], client)
        request = case.get("request", {})
        if case["case_id"] == "duplicate_team_member":
            user_id = context["users"]["member"]["id"]
        else:
            user_id = request.get("user_id", context["users"]["outsider"]["id"])

        response = target.post(
            f"/teams/{context['team_id']}/members",
            json={"user_id": user_id, "role": request.get("role", "member")},
        )
        assert_response(response, case["expected"])


@allure.feature("团队成员管理")
@allure.story("修改团队成员角色")
class TestUpdateTeamMemberRole:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, team_member_context):
        context = team_member_context
        target = context["clients"][case["actor"]]
        member_id = context["member_id"]("member")
        response = target.patch(
            f"/teams/{context['team_id']}/members/{member_id}",
            json={"role": case["request"]["role"]},
        )
        assert_response(response, case["expected"])
        assert_values(response, {"id": member_id, "role": "admin"})

    @pytest.mark.parametrize("case", update_fail, ids=_ids(update_fail))
    def test_update_fail(self, case, team_member_context, client):
        context = team_member_context
        target = _client(context, case["actor"], client)
        request = case.get("request", {})
        if case["case_id"] == "update_team_owner_role":
            member_id = context["member_id"]("owner")
        elif case["case_id"] == "cross_team_update_member":
            member_id = context["make_other_team"]()["member_id"]
        else:
            member_id = request.get("member_id", context["member_id"]("member"))

        response = target.patch(
            f"/teams/{context['team_id']}/members/{member_id}",
            json={"role": request.get("role", "admin")},
        )
        assert_response(response, case["expected"])


@allure.feature("团队成员管理")
@allure.story("移除团队成员")
class TestRemoveTeamMember:

    @pytest.mark.parametrize("case", remove_success, ids=_ids(remove_success))
    def test_remove_success(self, case, team_member_context):
        context = team_member_context
        target = context["clients"][case["actor"]]
        member_id = context["member_id"]("member")
        response = target.delete(f"/teams/{context['team_id']}/members/{member_id}")
        assert_response(response, case["expected"])

        again = context["clients"]["owner"].get(
            f"/teams/{context['team_id']}/members"
        )
        assert again.status_code == 200
        assert all(row["id"] != member_id for row in again.json())

    @pytest.mark.parametrize("case", remove_fail, ids=_ids(remove_fail))
    def test_remove_fail(self, case, team_member_context, client):
        context = team_member_context
        target = _client(context, case["actor"], client)
        request = case.get("request", {})
        if case["case_id"] == "remove_team_owner":
            member_id = context["member_id"]("owner")
        elif case["case_id"] == "cross_team_remove_member":
            member_id = context["make_other_team"]()["member_id"]
        else:
            member_id = request.get("member_id", context["member_id"]("member"))

        response = target.delete(f"/teams/{context['team_id']}/members/{member_id}")
        assert_response(response, case["expected"])


@allure.feature("团队成员管理")
@allure.story("候选成员搜索")
class TestSearchTeamMemberCandidates:

    @pytest.mark.parametrize("case", search_success, ids=_ids(search_success))
    def test_search_success(self, case, team_member_context):
        context = team_member_context
        target = context["clients"][case["actor"]]
        keyword = context["users"]["outsider"]["username"]
        response = target.get(
            f"/teams/{context['team_id']}/member-candidates",
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
    def test_search_fail(self, case, team_member_context, client):
        context = team_member_context
        target = _client(context, case["actor"], client)
        keyword = case.get("request", {}).get(
            "keyword",
            context["users"]["outsider"]["username"],
        )
        response = target.get(
            f"/teams/{context['team_id']}/member-candidates",
            params={"keyword": keyword},
        )
        assert_response(response, case["expected"])
