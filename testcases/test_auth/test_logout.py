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