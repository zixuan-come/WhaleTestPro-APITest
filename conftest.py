import pytest
import httpx
from config import BASE_URL, USERNAME, PASSWORD


@pytest.fixture(scope="session")
def login_data():
    resp = httpx.post(f"{BASE_URL}/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return resp.json()


@pytest.fixture(scope="session")
def access_token(login_data):
    return login_data["access_token"]


@pytest.fixture(scope="session")
def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}





