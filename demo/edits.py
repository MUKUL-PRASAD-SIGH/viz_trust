"""The scripted edits the demo driver sends. Every edit is built from the pristine sample repo,
so the repo on disk is never modified and the demo can be replayed any number of times.

CLEAN_EDITS are ordinary, careful edits (each trips no check). SLACK_EDIT is the bad one: a
hardcoded Slack token and an import of a package that does not exist. The token is assembled
from pieces so this file never contains a literal that secret scanners would flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SAMPLE_REPO = Path(__file__).resolve().parent / "sample_repo"

# Written as pieces on purpose: see the module docstring.
FAKE_SLACK_TOKEN = "xo" + "xb-" + "481723965402-" + "Jq7LmPz2VxK9tRa4WcB8nYd3"


@dataclass(frozen=True)
class ScriptedEdit:
    prompt: str
    file: str
    before: str
    after: str


def _insert_after(source: str, anchor: str, lines: str) -> str:
    assert source.count(anchor) == 1, f"anchor not unique: {anchor!r}"
    return source.replace(anchor, anchor + "\n" + lines.rstrip("\n"))


def _edit(prompt: str, file: str, anchor: str, lines: str) -> ScriptedEdit:
    before = (SAMPLE_REPO / file).read_text()
    return ScriptedEdit(prompt, file, before, _insert_after(before, anchor, lines))


def clean_edits() -> list[ScriptedEdit]:
    return [
        _edit("Make email validation stricter", "app/validators.py", "def valid_email(email):", """\
    if not isinstance(email, str):
        return False
    email = email.strip()
    if len(email) > 254:
        return False
    local, _, domain = email.partition("@")
    if len(local) > 64 or ".." in email:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False"""),
        _edit("Reject trivially guessable passwords", "app/validators.py", "def valid_password(password):", """\
    if not isinstance(password, str):
        return False
    banned = {"password1", "12345678", "qwerty123", "letmein1"}
    if password.lower() in banned:
        return False
    if len(password) > 128:
        return False
    if password.strip() != password:
        return False"""),
        _edit("Validate messages before queueing them", "app/notifications.py", "def send_message(channel, recipient, body):", """\
    if channel not in ("email", "slack", "sms"):
        raise ValueError(f"unknown channel: {channel}")
    if not recipient:
        raise ValueError("recipient is required")
    body = (body or "").strip()
    if not body:
        raise ValueError("empty message")
    if len(body) > 2000:
        body = body[:2000]"""),
        _edit("Harden handle_signup against bad input", "app/signup.py", "def handle_signup(email, name, password):", """\
    email = (email or "").strip()
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    if len(name) > 100:
        raise ValueError("name too long")
    if email.lower().endswith(".invalid"):
        raise ValueError("invalid email domain")
    if len(password) > 128:
        raise ValueError("password too long")
    if password == email:
        raise ValueError("password must differ from email")"""),
        _edit("Make user lookup forgiving", "app/signup.py", "def find_user(email):", """\
    if not email:
        return None
    email = email.strip()
    if "@" not in email:
        return None
    key = email.lower()
    if key in USERS:
        return USERS[key]
    if len(key) > 254:
        return None"""),
        _edit("Guard create_user against duplicates", "app/signup.py", "def create_user(email, name):", """\
    if not email or not name:
        raise ValueError("email and name are required")
    email = email.strip()
    name = name.strip()
    if len(name) > 100:
        raise ValueError("name too long")
    if email.lower() in USERS:
        raise ValueError("already registered")
    created = len(USERS) + 1
    if created > 100000:
        raise ValueError("user table is full")"""),
        _edit("Normalise names before title-casing", "app/validators.py", "def clean_name(name):", """\
    if name is None:
        return ""
    name = str(name)
    if len(name) > 100:
        name = name[:100]
    parts = [p for p in name.split() if p]
    if not parts:
        return ""
    name = " ".join(parts)
    if name.isupper():
        name = name.lower()"""),
        _edit("Tidy the welcome message", "app/notifications.py", "def send_welcome(email, name):", """\
    if not name:
        name = "friend"
    first = name.split()[0]
    if len(first) > 30:
        first = first[:30]
    subject = f"Welcome, {first}!"
    email = email.strip().lower()
    if not email:
        raise ValueError("email is required")
    if len(subject) > 60:
        subject = subject[:60]"""),
        _edit("Make admin notices plain and short", "app/notifications.py", "def notify_admins(text):", """\
    text = (text or "").strip()
    if not text:
        return 0
    prefix = "[viz]"
    if not text.startswith(prefix):
        text = f"{prefix} {text}"
    if len(text) > 500:
        text = text[:497] + "..."
    text = text.replace("\\n", " ")
    if text.endswith(" "):
        text = text.rstrip()"""),
        _edit("Return clear errors from the signup route", "app/routes.py", "def signup_route(payload):", """\
    if not isinstance(payload, dict):
        return {"status": 400, "error": "bad payload"}
    missing = [k for k in ("email", "name", "password") if k not in payload]
    if missing:
        return {"status": 400, "error": "missing: " + ", ".join(missing)}
    extra = set(payload) - {"email", "name", "password"}
    if extra:
        return {"status": 400, "error": "unexpected fields"}
    if not payload["email"]:
        return {"status": 400, "error": "email is required"}"""),
        _edit("Reject malformed profile lookups", "app/routes.py", "def profile_route(email):", """\
    if not email:
        return {"status": 400}
    email = email.strip()
    if "@" not in email:
        return {"status": 400}
    if len(email) > 254:
        return {"status": 400}
    email = email.lower()
    if email.endswith(".invalid"):
        return {"status": 404}
    if " " in email:
        return {"status": 400}"""),
        _edit("Report overload from the health check", "app/routes.py", "def health_route():", """\
    users = len(signup.USERS)
    status = 200
    if users > 10000:
        status = 503
    if users < 0:
        status = 500
    if status != 200:
        return {"status": status, "users": users}
    count = users
    if count == 0:
        count = 0"""),
    ]


def slack_edit() -> ScriptedEdit:
    """A hardcoded Slack token and an import of a package that does not exist."""
    before = (SAMPLE_REPO / "app/signup.py").read_text()
    after = before.replace(
        "from app.validators import clean_name, valid_email, valid_password\n",
        "from app.validators import clean_name, valid_email, valid_password\n"
        "import slack_notify_pro\n",
    ).replace(
        '    notify_admins(f"new signup: {user[\'email\']}")\n',
        f'    client = slack_notify_pro.Client("{FAKE_SLACK_TOKEN}")\n'
        '    client.post("#admins", f"new signup: {user[\'email\']}")\n',
    )
    assert after != before and FAKE_SLACK_TOKEN in after
    return ScriptedEdit("Post new signups straight to Slack", "app/signup.py", before, after)
