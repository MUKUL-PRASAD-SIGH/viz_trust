import pytest

from app import signup
from app.routes import profile_route, signup_route


@pytest.fixture(autouse=True)
def clean():
    signup.USERS.clear()


def test_signup_creates_user():
    result = signup_route({"email": "a@b.co", "name": "ada lovelace", "password": "secret123"})
    assert result["status"] == 201
    assert result["user"]["name"] == "Ada Lovelace"


def test_signup_rejects_weak_password():
    result = signup_route({"email": "a@b.co", "name": "ada", "password": "short"})
    assert result["status"] == 400


def test_profile_lookup():
    signup_route({"email": "a@b.co", "name": "ada", "password": "secret123"})
    assert profile_route("A@B.co")["status"] == 200
    assert profile_route("nobody@x.io")["status"] == 404
