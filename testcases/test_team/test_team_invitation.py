import allure
import pytest

from common.assert_util import assert_response
from common.yaml_util import load_yaml


success_cases = load_yaml("data/team/list_team_invitations.yaml")[
    "list_team_invitations_success"
]
fail_cases = load_yaml("data/team/list_team_invitations.yaml")[
    "list_team_invitations_fail"
]
consistency_cases = load_yaml("data/team/list_team_invitations.yaml")[
    "invitation_consistency"
]


def _ids(cases):
    return [case["case_id"] for case in cases]


@allure.feature("团队邀请")
@allure.story("邀请列表分页")
class TestListTeamInvitations:

    @pytest.mark.parametrize("case", success_cases, ids=_ids(success_cases))
    def test_pending_invitation_page(self, case, team_member_context):
        context = team_member_context
        invitee = context["users"]["outsider"]
        created = context["clients"]["owner"].post(
            f"/teams/{context['team_id']}/invitations",
            json={"user_id": invitee["id"], "role": "member"},
        )
        assert created.status_code == 201, f"邀请创建失败: {created.text}"
        invitation_id = created.json()["id"]

        try:
            response = invitee["client"].get(
                "/teams/invitations",
                params=case["request"],
            )
            assert_response(response, case["expected"])
            page = response.json()
            assert page["page"] == 1
            assert page["page_size"] == 1
            assert page["total"] >= 1
            assert page["total_pages"] >= 1
            assert [item["id"] for item in page["items"]] == [invitation_id]
            assert page["items"][0]["inviter"]["id"] > 0
            assert page["items"][0]["invitee"]["id"] == invitee["id"]
        finally:
            invitee["client"].post(
                f"/teams/invitations/{invitation_id}/respond",
                params={"accept": False},
            )

    @pytest.mark.parametrize("case", fail_cases, ids=_ids(fail_cases))
    def test_list_validation_and_auth(self, case, team_member_context, client):
        target = (
            client
            if case["actor"] == "anonymous"
            else team_member_context["users"]["outsider"]["client"]
        )
        response = target.get("/teams/invitations", params=case["request"])
        assert_response(response, case["expected"])


@allure.feature("团队邀请")
@allure.story("邀请并发与历史一致性")
class TestTeamInvitationConsistency:

    @pytest.mark.parametrize("case", consistency_cases, ids=_ids(consistency_cases))
    def test_invitation_consistency(self, case, team_member_context):
        context = team_member_context
        owner = context["clients"]["owner"]
        invitee = context["users"]["outsider"]
        invitee_client = invitee["client"]
        invite_path = f"/teams/{context['team_id']}/invitations"

        first = owner.post(
            invite_path,
            json={"user_id": invitee["id"], "role": "member"},
        )
        assert first.status_code == 201, f"邀请创建失败: {first.text}"
        first_id = first.json()["id"]

        if case["case_id"] == "duplicate_pending_invitation_returns_409":
            try:
                response = owner.post(
                    invite_path,
                    json={"user_id": invitee["id"], "role": "member"},
                )
                assert_response(response, case["expected"])
            finally:
                invitee_client.post(
                    f"/teams/invitations/{first_id}/respond",
                    params={"accept": False},
                )
            return

        if case["case_id"] == "repeated_response_returns_409":
            rejected = invitee_client.post(
                f"/teams/invitations/{first_id}/respond",
                params={"accept": False},
            )
            assert rejected.status_code == 200, f"首次拒绝失败: {rejected.text}"
            response = invitee_client.post(
                f"/teams/invitations/{first_id}/respond",
                params={"accept": False},
            )
            assert_response(response, case["expected"])
            return

        accepted = invitee_client.post(
            f"/teams/invitations/{first_id}/respond",
            params={"accept": True},
        )
        assert accepted.status_code == 200, f"首次接受失败: {accepted.text}"
        left = invitee_client.post(f"/teams/{context['team_id']}/leave")
        assert left.status_code == 200, f"退出团队失败: {left.text}"

        second = owner.post(
            invite_path,
            json={"user_id": invitee["id"], "role": "member"},
        )
        assert second.status_code == 201, f"再次邀请失败: {second.text}"
        response = invitee_client.post(
            f"/teams/invitations/{second.json()['id']}/respond",
            params={"accept": True},
        )
        try:
            assert_response(response, case["expected"])
            assert response.json()["status"] == "accepted"
        finally:
            invitee_client.post(f"/teams/{context['team_id']}/leave")
