"""Reads the firm's outgoing mail settings, the root-only file written at onboarding.

    firm_mail.py check FILE      prints what will be set, without the password
    firm_mail.py payload FILE    prints the settings for Odoo, base64 (root keeps it in a variable)
    firm_mail.py request SPOOL FILE
                                 reads what the console asked (the "Email for this firm" screen),
                                 erases SPOOL, writes FILE (chmod 600) when settings were sent, and
                                 prints "REF set", "REF off" or "REF refused"

The file is read, never sourced or run. It must be a plain file owned by the user running this
(root on a server) and readable by nobody else (chmod 600). One setting per line, KEY=value:

    MAIL_HOST=smtp.example.cm
    MAIL_PORT=587
    MAIL_ENCRYPTION=starttls        (or ssl; a password never travels unencrypted)
    MAIL_USER=cabinet@example.cm
    MAIL_PASSWORD=...
    MAIL_FROM=cabinet@example.cm    (the sender address, or the firm's domain)

Pure Python, no Odoo: run with python -I. Exit 2 with one line on stderr when the file is refused;
no message ever quotes a line of the file, so the password cannot reach a terminal or a log.
"""
import base64
import ipaddress
import json
import os
import re
import stat
import sys

KEYS = ("MAIL_HOST", "MAIL_PORT", "MAIL_ENCRYPTION", "MAIL_USER", "MAIL_PASSWORD", "MAIL_FROM")
REQUIRED = ("MAIL_HOST", "MAIL_PORT", "MAIL_ENCRYPTION", "MAIL_FROM")
PORTS = (25, 465, 587, 2525)
ENCRYPTIONS = ("starttls", "ssl")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOST = re.compile(r"^(?=.{1,253}$)%s(?:\.%s)+$" % (_LABEL, _LABEL))
SENDER = re.compile(r"^(?:[A-Za-z0-9._%%+-]{1,64}@)?(?=.{1,253}$)%s(?:\.%s)+$" % (_LABEL, _LABEL))
USER = re.compile(r"^[^\s\x00-\x1f]{1,254}$")
MAX_PASSWORD = 512
# What the console's heartbeat answer may carry (see ea_audit_firm_agent/services/collect.py).
REF = re.compile(r"^[0-9a-f]{16}$")
REQUEST_SET_KEYS = frozenset({"ref", "action", "host", "port", "encryption", "user", "password", "from"})
REQUEST_OFF_KEYS = frozenset({"ref", "action"})
MAX_REQUEST_BYTES = 4096


class MailFileError(ValueError):
    pass


def check_file(path, owner_uid):
    try:
        info = os.lstat(path)
    except OSError:
        raise MailFileError("the file is missing") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MailFileError("not a plain file")
    if info.st_uid != owner_uid:
        raise MailFileError("the file must belong to the user running this script")
    if info.st_mode & 0o077:
        raise MailFileError("others can read the file: chmod 600")
    if info.st_size > 4096:
        raise MailFileError("the file is too large")


def parse(text):
    """dict(host, port, encryption, user, password, from_filter), or MailFileError."""
    values = {}
    for number, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in KEYS:
            raise MailFileError("line %d: not one of %s" % (number, ", ".join(KEYS)))
        if key in values:
            raise MailFileError("line %d: %s given twice" % (number, key))
        values[key] = value if key == "MAIL_PASSWORD" else value.strip()
    missing = [key for key in REQUIRED if not values.get(key)]
    if missing:
        raise MailFileError("missing: %s" % ", ".join(missing))
    host = values["MAIL_HOST"].lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise MailFileError("MAIL_HOST: local or private addresses are refused")
    elif not HOST.match(host) or host == "localhost" or host.endswith(".localhost"):
        raise MailFileError("MAIL_HOST: not a server name")
    if not values["MAIL_PORT"].isdigit() or int(values["MAIL_PORT"]) not in PORTS:
        raise MailFileError("MAIL_PORT: 25, 465, 587 or 2525")
    encryption = values["MAIL_ENCRYPTION"].lower()
    if encryption not in ENCRYPTIONS:
        raise MailFileError("MAIL_ENCRYPTION: starttls or ssl")
    user, password = values.get("MAIL_USER", ""), values.get("MAIL_PASSWORD", "")
    if bool(user) != bool(password):
        raise MailFileError("MAIL_USER and MAIL_PASSWORD go together")
    if user and not USER.match(user):
        raise MailFileError("MAIL_USER: no spaces or control characters")
    if len(password) > MAX_PASSWORD or any(ord(c) < 32 for c in password):
        raise MailFileError("MAIL_PASSWORD: too long, or a control character")
    sender = values["MAIL_FROM"]
    if not SENDER.match(sender):
        raise MailFileError("MAIL_FROM: an address or a domain")
    return {
        "host": host,
        "port": int(values["MAIL_PORT"]),
        "encryption": encryption,
        "user": user,
        "password": password,
        "from_filter": sender.lower(),
    }


def describe(settings):
    return "%s:%s %s, user %s, sender %s, password %s" % (
        settings["host"], settings["port"], settings["encryption"].upper(),
        settings["user"] or "none", settings["from_filter"], "given" if settings["password"] else "none",
    )


def env_text(host, port, encryption, user, password, sender):
    """The settings file, as an operator would write it by hand. Refuses a line break in a value."""
    values = (host, str(port), encryption, user, password, sender)
    if any("\n" in value or "\r" in value for value in values):
        raise MailFileError("a value holds a line break")
    return "".join("%s=%s\n" % pair for pair in zip(KEYS, values))


def read_request(text):
    """(ref, action, file text or None) from the console's request, or MailFileError.

    The request was checked by the console, by the agent, and is checked here again with the same
    rules as a file written by hand: the spool folder is writable by the odoo user.
    """
    try:
        data = json.loads(text)
    except ValueError:
        raise MailFileError("the request is not JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("ref"), str) or not REF.match(data["ref"]):
        raise MailFileError("the request has no reference")
    action = data.get("action")
    if action == "off":
        if set(data) != REQUEST_OFF_KEYS:
            raise RequestRefused(data["ref"], "unexpected keys")
        return data["ref"], "off", None
    if action != "set" or set(data) != REQUEST_SET_KEYS:
        raise RequestRefused(data["ref"], "not a request this script knows")
    port = data["port"]
    strings = [data[key] for key in ("host", "encryption", "user", "password", "from")]
    if type(port) is not int or not all(isinstance(value, str) for value in strings):
        raise RequestRefused(data["ref"], "a value of the wrong type")
    try:
        text = env_text(data["host"], port, data["encryption"], data["user"], data["password"], data["from"])
        parse(text)
    except MailFileError as error:
        raise RequestRefused(data["ref"], str(error)) from None
    return data["ref"], "set", text


class RequestRefused(MailFileError):
    """A request whose reference is known: the console is told it was refused."""

    def __init__(self, ref, reason):
        super().__init__(reason)
        self.ref = ref


def take_request(spool):
    """The spool file's text, then the file is erased whatever it holds. MailFileError if unusable."""
    try:
        try:
            info = os.lstat(spool)
        except OSError:
            raise MailFileError("no request") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise MailFileError("the request is not a plain file")
        if info.st_size > MAX_REQUEST_BYTES:
            raise MailFileError("the request is too large")
        try:
            # No link followed, even one swapped in after the check above.
            handle = os.open(spool, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(handle, encoding="utf-8") as stream:
                return stream.read(MAX_REQUEST_BYTES + 1)
        except UnicodeDecodeError:
            raise MailFileError("the request is not UTF-8 text") from None
        except OSError:
            raise MailFileError("the request cannot be read") from None
    finally:
        try:
            os.unlink(spool)
        except FileNotFoundError:
            pass


def write_private(path, text):
    """Writes FILE for the user running this only (chmod 600), in one step."""
    folder = os.path.dirname(os.path.abspath(path))
    temporary = os.path.join(folder, ".mail.env.%d" % os.getpid())
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def request_main(spool, path):
    try:
        ref, action, text = read_request(take_request(spool))
    except RequestRefused as error:
        print("refused: %s" % error, file=sys.stderr)
        print("%s refused" % error.ref)
        return 0
    except MailFileError as error:
        print("refused: %s" % error, file=sys.stderr)
        return 2
    if text is not None:
        write_private(path, text)
    print("%s %s" % (ref, action))
    return 0


def payload(settings):
    return base64.b64encode(json.dumps(settings).encode("utf-8")).decode("ascii")


def main(argv):
    if len(argv) == 4 and argv[1] == "request":
        return request_main(argv[2], argv[3])
    if len(argv) != 3 or argv[1] not in ("check", "payload"):
        print("usage: firm_mail.py check|payload FILE, or firm_mail.py request SPOOL FILE", file=sys.stderr)
        return 2
    path = argv[2]
    try:
        check_file(path, os.getuid())
        with open(path, encoding="utf-8") as handle:
            settings = parse(handle.read())
    except UnicodeDecodeError:
        print("refused: the file is not UTF-8 text", file=sys.stderr)
        return 2
    except MailFileError as error:
        print("refused: %s" % error, file=sys.stderr)
        return 2
    print(describe(settings) if argv[1] == "check" else payload(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
