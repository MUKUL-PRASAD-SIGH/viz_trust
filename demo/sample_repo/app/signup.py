"""Creating accounts."""

from app.notifications import notify_admins, send_welcome
from app.validators import clean_name, valid_email, valid_password

USERS = {}


def find_user(email):
    return USERS.get(email.lower())


def create_user(email, name):
    user = {"email": email.lower(), "name": clean_name(name)}
    USERS[user["email"]] = user
    return user


def handle_signup(email, name, password):
    if not valid_email(email):
        raise ValueError("invalid email")
    if not valid_password(password):
        raise ValueError("weak password")
    if find_user(email):
        raise ValueError("already registered")
    user = create_user(email, name)
    send_welcome(user["email"], user["name"])
    notify_admins(f"new signup: {user['email']}")
    return user
