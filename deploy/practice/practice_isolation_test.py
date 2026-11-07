#!/usr/bin/python3 -I
"""Isolation of the practice spaces, tested against the running service. As root, on the computer.

    practice_isolation_test.py SPACE_A SPACE_B [--preview-url https://host:port] [--intruders]

--intruders also makes two throwaway databases the scripts did not make (practice_ci-firmdump,
practice_ci-copy), checks that practice-guard refuses and closes each, and drops them.

Uses the first administrators of two spaces (their files in secrets/logins, never printed) and
proves, against Odoo itself and, with --preview-url, through nginx:

  - each one logs into its own space, by its own host name;
  - neither logs into the other space: not by the other's host name, not with ?db=, not with the
    X-Odoo-Database header, not by sending a database name to /web/session/authenticate;
  - a session of space A is worth nothing on host B, and is logged out by trying;
  - no database list, no database manager; an unknown name and the template's name open nothing;
  - the template's accounts (admin/admin, demo/demo, the demonstration people) have no password;
  - the practice service's PostgreSQL role cannot read the other databases of the machine.

Standard library only. Prints one line per check and exits 1 if any failed.
"""

import http.client
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.parse

ETC = "/etc/auditisa-practice"
DEMO_LOGINS = ("jp.mbarga@cabinet-demo.example", "m.ndongo@cabinet-demo.example")

FAILED = []


def check(name, condition):
    print(("ok      " if condition else "FAILED  ") + name)
    if not condition:
        FAILED.append(name)


def env_file(path):
    out = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = re.match(r"^([A-Za-z0-9_]+)='?([^'\n]*)'?$", line.rstrip("\n"))
            if match:
                out[match.group(1)] = match.group(2)
    return out


def login_of(slug):
    values = {}
    with open(os.path.join(ETC, "secrets", "logins", slug), encoding="utf-8") as handle:
        for line in handle:
            key, _, value = line.rstrip("\n").partition("=")
            values[key] = value
    return values["login"], values["password"]


class Client:
    """One HTTP target: Odoo directly with a Host header, or nginx over HTTPS."""

    def __init__(self, base, host=None):
        self.url = urllib.parse.urlsplit(base)
        self.host = host
        self.cookies = {}

    def request(self, method, path, body=None, headers=None, raw=None):
        if self.url.scheme == "https":
            connection = http.client.HTTPSConnection(self.url.hostname, self.url.port or 443, timeout=90,
                                                     context=ssl.create_default_context())
        else:
            connection = http.client.HTTPConnection(self.url.hostname, self.url.port or 80, timeout=90)
        all_headers = dict(headers or {})
        if self.host:
            all_headers["Host"] = self.host
        if self.cookies:
            all_headers["Cookie"] = "; ".join("%s=%s" % item for item in self.cookies.items())
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            all_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=data, headers=all_headers)
        response = connection.getresponse()
        content = response.read()
        for header, value in response.getheaders():
            if header.lower() == "set-cookie":
                name, _, rest = value.partition("=")
                self.cookies[name.strip()] = rest.split(";", 1)[0]
        connection.close()
        return response.status, content

    def rpc(self, path, params, headers=None):
        status, content = self.request("POST", path, {"jsonrpc": "2.0", "method": "call", "params": params, "id": 1}, headers)
        try:
            return status, json.loads(content)
        except ValueError:
            return status, {}

    def authenticate(self, database, login, password, headers=None):
        status, answer = self.rpc("/web/session/authenticate", {"db": database, "login": login, "password": password}, headers)
        result = answer.get("result") or {}
        return status == 200 and bool(result.get("uid"))

    def uid(self):
        _status, answer = self.rpc("/web/session/get_session_info", {})
        return (answer.get("result") or {}).get("uid")


def psql(sql, database="postgres"):
    return subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-XAt", "-d", database, "-c", sql],
                          capture_output=True, text=True, check=False)


def database_exists(name):
    return psql("SELECT 1 FROM pg_database WHERE datname = '%s'" % name).stdout.strip() == "1"


def guard_refuses():
    return subprocess.run(["/usr/local/sbin/practice-guard", "check"], capture_output=True, text=True, check=False).returncode != 0


def intruder_checks(slug_a):
    """Databases the scripts did not make: a firm's dump, and a copy of the template made by hand."""
    print("== the guard (throwaway databases practice_ci-*)")
    check("the guard passes before", not guard_refuses())
    for name, setup in (
        ("practice_ci-firmdump", ["createdb", "-T", "template0", "practice_ci-firmdump"]),
        ("practice_ci-copy", ["createdb", "-T", "tpl_practice_demo", "practice_ci-copy"]),
    ):
        made = subprocess.run(["runuser", "-u", "postgres", "--"] + setup, capture_output=True, text=True, check=False)
        if made.returncode != 0:
            check("could make %s" % name, False)
            continue
        if name.endswith("firmdump"):
            psql("CREATE TABLE ir_config_parameter (key varchar, value text);"
                 " INSERT INTO ir_config_parameter VALUES ('ea_firm_agent.slug', 'cabinet-x')", name)
        check("the guard refuses %s" % name, guard_refuses())
        closed = psql("SELECT datallowconn FROM pg_database WHERE datname = '%s'" % name).stdout.strip()
        check("...and closes it to connections", closed == "f")
        psql('DROP DATABASE "%s" WITH (FORCE)' % name)
    check("the guard passes again once they are dropped", not guard_refuses())


def main(argv):
    if len(argv) < 3 or os.geteuid() != 0:
        print(__doc__)
        return 64
    slug_a, slug_b = argv[1], argv[2]
    preview = argv[argv.index("--preview-url") + 1] if "--preview-url" in argv else None
    settings = env_file(os.path.join(ETC, "practice.env"))
    domain, port = settings["PRACTICE_DOMAIN"], settings["PRACTICE_PORT"]
    odoo = "http://127.0.0.1:%s" % port
    db_a, db_b = "practice_" + slug_a, "practice_" + slug_b
    login_a, password_a = login_of(slug_a)
    login_b, password_b = login_of(slug_b)
    host_a, host_b = "%s.%s" % (slug_a, domain), "%s.%s" % (slug_b, domain)

    print("== Odoo, chosen by host name")
    a = Client(odoo, host_a)
    check("A's administrator logs into A", a.authenticate(db_a, login_a, password_a))
    check("A's session is open on A", bool(a.uid()))
    b = Client(odoo, host_b)
    check("B's administrator logs into B", b.authenticate(db_b, login_b, password_b))

    check("A's login and password do not open B", not Client(odoo, host_b).authenticate(db_b, login_a, password_a))
    check("host B refuses A's database by name", not Client(odoo, host_b).authenticate(db_a, login_a, password_a))
    check("host A refuses B's database by name", not Client(odoo, host_a).authenticate(db_b, login_b, password_b))
    check("host A refuses B's database by header",
          not Client(odoo, host_a).authenticate(db_b, login_b, password_b, {"X-Odoo-Database": db_b}))
    via_query = Client(odoo, host_a)
    via_query.request("GET", "/web/login?db=" + db_b)
    check("host A with ?db=B still does not take B's login", not via_query.authenticate(db_b, login_b, password_b))

    stolen = Client(odoo, host_b)
    stolen.cookies = dict(a.cookies)
    check("A's session cookie gives nothing on host B", not stolen.uid())

    status, answer = Client(odoo, host_a).rpc("/web/database/list", {})
    check("no database list", "result" not in answer)
    status, content = Client(odoo, host_a).request("GET", "/web/database/manager")
    check("the database manager says it is disabled", b"disabled by the administrator" in content)
    boundary = "practiceboundary"
    form = "".join(
        "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)
        for k, v in (("master_pwd", "admin"), ("name", "practice_ci-restored"))
    ) + "--%s\r\nContent-Disposition: form-data; name=\"backup_file\"; filename=\"x.zip\"\r\n\r\nPK\r\n--%s--\r\n" % (boundary, boundary)
    restore = Client(odoo, host_a)
    restore.request("POST", "/web/database/restore", None, {"Content-Type": "multipart/form-data; boundary=" + boundary}, raw=form.encode())
    check("a dump cannot be restored through Odoo", not database_exists("practice_ci-restored"))

    for label, host in (("an unknown name", "nosuch." + domain), ("the template's name", "tpl." + domain),
                        ("a name with an underscore", "_template." + domain), ("the bare domain", domain)):
        status, _content = Client(odoo, host).request("GET", "/web/login")
        check("%s opens no space (%s)" % (label, status), status != 200)

    for slug, database, host in ((slug_a, db_a, host_a), (slug_b, db_b, host_b)):
        for login, password in (("admin", "admin"), ("demo", "demo"), ("portal", "portal")) + tuple((d, "") for d in DEMO_LOGINS):
            check("%s: no access as %s with a well-known or empty password" % (slug, login),
                  not Client(odoo, host).authenticate(database, login, password))

    if "--intruders" in argv:
        intruder_checks(slug_a)

    print("== PostgreSQL")
    others = subprocess.run(
        ["runuser", "-u", "postgres", "--", "psql", "-XAt", "-c",
         "SELECT datname FROM pg_database WHERE datallowconn AND datname NOT IN ('postgres', 'template1') "
         "AND datname NOT LIKE 'practice\\_%' ORDER BY 1 LIMIT 3"],
        capture_output=True, text=True, check=False).stdout.split()
    for database in others:
        result = subprocess.run(
            ["runuser", "-u", "postgres", "--", "psql", "-XAt", "-d", database, "-c",
             "SET ROLE odoo_practice; SELECT count(*) FROM res_users"],
            capture_output=True, text=True, check=False)
        check("the practice role cannot read %s" % database, result.returncode != 0)
    if not others:
        print("NOTE    no other database on this machine")

    if preview:
        print("== through nginx: " + preview)
        anyone = Client(preview)
        status, _content = anyone.request("GET", "/web/login")
        check("without a chosen space nothing reaches Odoo (%s)" % status, status == 403)
        pa = Client(preview)
        status, _content = pa.request("GET", "/practice/" + slug_a)
        check("the link to A sets the space", status == 302 and pa.cookies.get("ea_practice_space") == slug_a)
        status, _content = pa.request("GET", "/web/database/manager")
        check("no database manager through nginx (%s)" % status, status == 404)
        status, _content = pa.request("GET", "/web/database/selector")
        check("no database selector through nginx (%s)" % status, status == 404)
        check("A's administrator logs into A through nginx", pa.authenticate(db_a, login_a, password_a))
        check("B's login does not open A through nginx", not Client(preview).authenticate(db_b, login_b, password_b))
        crossed = Client(preview)
        crossed.request("GET", "/practice/" + slug_a)
        check("B's login and database name with A chosen: refused",
              not crossed.authenticate(db_b, login_b, password_b, {"X-Odoo-Database": db_b}))
        pa.cookies["ea_practice_space"] = slug_b
        check("A's session is worth nothing once B is chosen", not pa.uid())
        forged = Client(preview)
        forged.cookies["ea_practice_space"] = "tpl_practice_demo"
        status, _content = forged.request("GET", "/web/login")
        check("a forged space cookie opens nothing (%s)" % status, status == 403)

    print("%d check(s) failed" % len(FAILED) if FAILED else "ISOLATED: every check passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
