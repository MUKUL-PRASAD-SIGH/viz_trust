"""HTTP-shaped entry points (plain functions, no web framework needed for the demo)."""

from app import signup
from app.signup import find_user, handle_signup


def signup_route(payload):
    try:
        user = handle_signup(payload["email"], payload["name"], payload["password"])
    except ValueError as err:
        return {"status": 400, "error": str(err)}
    return {"status": 201, "user": user}


def profile_route(email):
    user = find_user(email)
    if user is None:
        return {"status": 404}
    return {"status": 200, "user": user}


def health_route():
    return {"status": 200, "users": len(signup.USERS)}
