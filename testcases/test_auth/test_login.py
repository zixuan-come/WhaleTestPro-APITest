import pytest
import allure
from config import USERNAME, PASSWORD
from common.yaml_util import load_yaml
from common.assert_util import assert_response

cases = load_yaml("data/login.yaml")["login_fail"]

@allure.feature("用户认证")
@allure.story("用户登录")
class TestLogin:

    @pytest.mark.smoke
    def test_login_success(self, client):
        resp = client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
        assert resp.status_code == 200, f"登录失败: {resp.json()}"
        data = resp.json()
        assert "access_token" in data, "缺少 access_token"
        assert "token_type" in data, "缺少 token_type"

    @pytest.mark.parametrize("case", cases, ids=[case["case_id"] for case in cases])
    def test_login_fail(self, client, case):
        resp = client.post(
            "/auth/login",
            json=case["request"]
        )
        assert_response(resp, case["expected"])



