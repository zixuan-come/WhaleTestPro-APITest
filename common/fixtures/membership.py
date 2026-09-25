"""Team role fixtures; resources remain registered and owned by this run."""
import uuid
import pytest
from config import BASE_URL, PASSWORD
from common.request_util import RequestUtil
from common.fixtures.authentication import clear_login_rate_limit


@pytest.fixture(scope="session")
def member_users(client, ensure_test_user):
    """创建成员权限测试所需的三种独立身份，并返回其黑盒客户端。"""
    users = {}
    role_prefixes = {"admin": "adm", "member": "mem", "outsider": "out"}

    for role in ("admin", "member", "outsider"):
        username = f"api_{role_prefixes[role]}_{uuid.uuid4().hex[:8]}"
        password = PASSWORD

        register = client.post(
            "/auth/register",
            json={"username": username, "password": password},
        )
        assert register.status_code == 201, (
            f"成员测试账号注册失败: role={role}, response={register.text}"
        )

        clear_login_rate_limit()
        login = client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200, (
            f"成员测试账号登录失败: role={role}, response={login.text}"
        )

        token = login.json()["access_token"]
        users[role] = {
            "id": register.json()["id"],
            "username": username,
            "token": token,
            "client": RequestUtil(
                BASE_URL,
                headers={"Authorization": f"Bearer {token}"},
            ),
        }

    return users


@pytest.fixture
def team_member_context(auth_client, member_users, unique_name, team_factory):
    """创建 owner/admin/member 团队上下文，供团队成员黑盒用例复用。"""
    project_ids = []
    team_ids = []
    explicit_team_id = team_factory()
    created = auth_client.post(
        "/projects",
        json={
            "name": unique_name("auto_team_member_project_"),
            "description": "团队成员管理接口自动化测试项目",
            "team_id": explicit_team_id,
        },
    )
    assert created.status_code == 201, f"成员测试项目创建失败: {created.text}"
    project_id = created.json()["id"]
    team_id = created.json()["team_id"]
    project_ids.append(project_id)
    team_ids.append(team_id)

    for role in ("admin", "member"):
        response = auth_client.post(
            f"/teams/{team_id}/members",
            json={"user_id": member_users[role]["id"], "role": role},
        )
        assert response.status_code == 201, (
            f"成员测试前置关系创建失败: role={role}, response={response.text}"
        )

    members = auth_client.get(f"/teams/{team_id}/members")
    assert members.status_code == 200, f"成员测试前置查询失败: {members.text}"
    member_rows = members.json()
    member_ids = {row["user_id"]: row["id"] for row in member_rows}
    role_user_ids = {
        "owner": next(row["user_id"] for row in member_rows if row["role"] == "owner"),
        "admin": member_users["admin"]["id"],
        "member": member_users["member"]["id"],
    }

    other_team_cache = {}

    def make_other_team():
        """创建第二个项目和团队并加入 outsider，用于跨团队成员 ID 用例。"""
        if other_team_cache:
            return other_team_cache

        other = auth_client.post(
            "/projects",
            json={
                "name": unique_name("auto_member_other_team_"),
                "description": "跨团队成员权限测试项目",
                "team_id": team_factory(),
            },
        )
        assert other.status_code == 201, f"跨团队测试项目创建失败: {other.text}"
        other_id = other.json()["id"]
        other_team_id = other.json()["team_id"]
        project_ids.append(other_id)
        team_ids.append(other_team_id)

        added = auth_client.post(
            f"/teams/{other_team_id}/members",
            json={"user_id": member_users["outsider"]["id"], "role": "member"},
        )
        assert added.status_code == 201, f"跨团队测试成员创建失败: {added.text}"

        other_members = auth_client.get(f"/teams/{other_team_id}/members")
        assert other_members.status_code == 200, (
            f"跨团队测试成员查询失败: {other_members.text}"
        )
        outsider_id = next(
            row["id"]
            for row in other_members.json()
            if row["user_id"] == member_users["outsider"]["id"]
        )
        other_team_cache.update(
            {
                "project_id": other_id,
                "team_id": other_team_id,
                "member_id": outsider_id,
            }
        )
        return other_team_cache

    context = {
        "project_id": project_id,
        "team_id": team_id,
        "users": member_users,
        "clients": {
            "owner": auth_client,
            "admin": member_users["admin"]["client"],
            "member": member_users["member"]["client"],
            "outsider": member_users["outsider"]["client"],
        },
        "member_ids": member_ids,
        "member_id": lambda role: member_ids[role_user_ids[role]],
        "make_other_team": make_other_team,
    }

    try:
        yield context
    finally:
        for pid in reversed(project_ids):
            try:
                auth_client.delete(f"/projects/{pid}")
            except Exception:
                pass
        for tid in reversed(team_ids):
            try:
                auth_client.delete(f"/teams/{tid}")
            except Exception:
                pass
