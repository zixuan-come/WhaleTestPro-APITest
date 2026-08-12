"""通用契约反例：把所有走 X-Project-Id 的资源共有的边界行为集中参数化，
避免在每个资源文件里重复同样的断言。资源专属反例(mock 命中/重名等)仍留各自文件。

覆盖四类(均无需构造合法 body):
- 缺 X-Project-Id 头 → 422
- 不带 token → 401 Not authenticated
- 创建时缺必填字段(POST {}) → 422
- 详情路径 id 传非数字 → 422
"""
import allure
import pytest

from common.yaml_util import load_yaml
from common.assert_util import assert_response

resources = load_yaml("data/negative_contract.yaml")["resources"]
creatable = [r for r in resources if r["creatable"]]
detailed = [r for r in resources if r["has_detail"]]
updatable = [r for r in resources if r.get("updatable")]


def _names(rs):
    return [r["name"] for r in rs]


@allure.feature("通用契约")
@allure.story("边界与鉴权反例")
class TestNegativeContract:

    @pytest.mark.parametrize("res", resources, ids=_names(resources))
    def test_list_without_project_header(self, res, auth_client):
        """带 token 但缺 X-Project-Id 头 → 422(全资源一致)。"""
        resp = auth_client.get(res["path"])
        assert resp.status_code == 422, f"{res['name']} 缺项目头应 422: {resp.status_code} {resp.text}"

    @pytest.mark.parametrize("res", resources, ids=_names(resources))
    def test_list_without_token(self, res, project_only_client):
        """不带 token 访问项目资源列表 → 401 Not authenticated。"""
        resp = project_only_client.get(res["path"])
        assert_response(resp, {
            "status_code": res["list_no_token_status"],
            "detail": res["list_no_token_detail"],
        })

    @pytest.mark.parametrize("res", creatable, ids=_names(creatable))
    def test_create_missing_required_field(self, res, project_client):
        """创建时不给任何字段(POST {}) → 422 Pydantic 校验失败。"""
        resp = project_client.post(res["path"], json={})
        assert resp.status_code == 422, f"{res['name']} 缺字段应 422: {resp.status_code} {resp.text}"

    @pytest.mark.parametrize("res", detailed, ids=_names(detailed))
    def test_detail_invalid_id_type(self, res, project_client):
        """详情路径 id 传非数字 → 422(路径参数类型校验)。"""
        resp = project_client.get(f"{res['path']}/not-a-number")
        assert resp.status_code == 422, f"{res['name']} 非法 id 应 422: {resp.status_code} {resp.text}"

    @pytest.mark.parametrize("res", updatable, ids=_names(updatable))
    def test_update_not_found(self, res, project_client):
        """更新不存在的资源(PUT /{path}/999999,带合法 body) → 404。
        body 合法才能越过 Pydantic 校验、走到 handler 查库,验证的是"找不到"而非"参数错"。"""
        resp = project_client.put(f"{res['path']}/999999", json=res["update_body"])
        assert resp.status_code == 404, (
            f"{res['name']} 更新不存在 id 应 404: {resp.status_code} {resp.text}")
