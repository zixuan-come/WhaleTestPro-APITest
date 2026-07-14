import pytest
from config import BASE_URL, USERNAME, PASSWORD
from common.request_util import RequestUtil

TEST_PROJECT_NAME = "auto_test_project"

@pytest.fixture(scope="session")
def login_data(client):
    resp = client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return resp.json()


@pytest.fixture(scope="session")
def access_token(login_data):
    return login_data["access_token"]


@pytest.fixture(scope="session")
def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="session")
def client():
    return RequestUtil(BASE_URL)


@pytest.fixture(scope="session")
def auth_client(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    return RequestUtil(BASE_URL, headers=headers)


@pytest.fixture(scope="session")
def project_id(auth_client):
    resp = auth_client.get("/projects")
    assert resp.status_code == 200

    projects = resp.json()

    for project in projects:
        if project["name"] == TEST_PROJECT_NAME:
            return project["id"]

    create_resp = auth_client.post(
        "/projects",
        json={
            "name": TEST_PROJECT_NAME,
            "description": "接口自动化测试项目"
        }
    )
    assert create_resp.status_code == 201

    return create_resp.json()["id"]


@pytest.fixture(scope="session")
def project_headers(project_id):
    return {"X-Project-Id": str(project_id)}


@pytest.fixture(scope="session")
def project_client(access_token, project_id):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Project-Id": str(project_id)
    }
    return RequestUtil(BASE_URL, headers=headers)




