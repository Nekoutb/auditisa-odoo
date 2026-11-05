"""Reading stored messages in the reader's language. See services/messages.py."""

from ..services.messages import loads, render


def t(env, message):
    """One message, for an error or a notification in the current user's language."""
    return render(message, env._)


def read(env, raw):
    """What a column holds, one message per line, in the current user's language."""
    return "\n".join(render(message, env._) for message in loads(raw))
