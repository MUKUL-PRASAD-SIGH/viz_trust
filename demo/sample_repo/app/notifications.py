"""Outgoing messages. Nothing here talks to a real service in the sample app."""

OUTBOX = []


def send_message(channel, recipient, body):
    OUTBOX.append({"channel": channel, "to": recipient, "body": body})
    return len(OUTBOX)


def send_welcome(email, name):
    return send_message("email", email, f"Welcome, {name}!")


def notify_admins(text):
    return send_message("slack", "#admins", text)
