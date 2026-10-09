"""Input checks shared by signup and the routes."""

import re

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email):
    return bool(EMAIL.match(email))


def valid_password(password):
    return len(password) >= 8 and any(c.isdigit() for c in password)


def clean_name(name):
    return " ".join(name.split()).title()
