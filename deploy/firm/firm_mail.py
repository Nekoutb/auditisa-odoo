"""Reads the firm's outgoing mail settings, the root-only file written at onboarding.

    firm_mail.py check FILE      prints what will be set, without the password
    firm_mail.py payload FILE    prints the settings for Odoo, base64 (root keeps it in a variable)

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


def payload(settings):
    return base64.b64encode(json.dumps(settings).encode("utf-8")).decode("ascii")


def main(argv):
    if len(argv) != 3 or argv[1] not in ("check", "payload"):
        print("usage: firm_mail.py check|payload FILE", file=sys.stderr)
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
