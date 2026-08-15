import pytest
import allure
from common.yaml_util import load_yaml
from common.assert_util import assert_response


logout_success_cases = load_yaml("data/logout.yaml")["logout_success"]
logout_fail_cases = load_yaml("data/logout.yaml")["logout_fail"]


@allure.feature("用户认证")
@allure.story("退出登录")
class TestLogout:

    @pytest.mark.parametrize("case", logout_success_cases, ids=[case["case_id"] for case in logout_success_cases])
    def test_logout_success(self, client, disposable_token, case):
        # 用专用一次性账号的 token 注销,避免拉黑 admin 会话 token 污染其它用例
        resp = client.post("/auth/logout", headers={"Authorization": f"Bearer {disposable_token}"})
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", logout_fail_cases, ids=[case["case_id"] for case in logout_fail_cases])
    def test_logout_fail(self, client, case):
        resp = client.post("/auth/logout", headers=case["request"]["headers"])
        assert_response(resp, case["expected"])

    def test_logout_only_blacklists_current_token(self, client, disposable_token):
        second_login = client.post(
            "/auth/login",
            json={"username": "logout_bot", "password": "logout_bot_pwd"},
        )
        assert second_login.status_code == 200, second_login.text
        second_token = second_login.json()["access_token"]
        assert second_token != disposable_token

        logged_out = client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {disposable_token}"},
        )
        assert logged_out.status_code == 200, logged_out.text

        still_valid = client.get(
            "/projects",
            headers={"Authorization": f"Bearer {second_token}"},
        )
        assert still_valid.status_code == 200, still_valid.text
