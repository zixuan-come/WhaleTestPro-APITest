import pytest
from config import BASE_URL, USERNAME, PASSWORD
from common.request_util import HttpUtil

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
    return HttpUtil(BASE_URL)


