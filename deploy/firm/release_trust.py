#!/usr/bin/env python3
"""release_trust.py: the list of signers this server trusts for new releases. Standard library only.

    release_trust.py adopt DOC DIR [--legacy FILE]   takes the list in DOC if it is newer than DIR's
    release_trust.py check DOC                       checks DOC, prints its number
    release_trust.py serial DIR                      prints the number of the list in use (0: none)

WHO MAY CALL `adopt`: only root, and only with the deploy/trust/signers.json of a release this server
has VERIFIED with a key it already trusts: the release in use ($CURRENT/deploy/trust/signers.json),
or the one firm-update or practice-update has just checked. Never with a file from the spool, the
control plane or the network. That is the whole point: whoever breaks into the console cannot add a
key here, because a list only arrives inside a release signed by a signer this server already trusts.

A list is taken only if its number is HIGHER than the one in use: an older release, installed again,
cannot bring back a removed signer.

Layout of DIR (the same as the console writes at first boot, services/recipe.py):
    <fingerprint>.pub    one public key per signer
    <fingerprint>.only   beside a REMOVED signer's key: the bundle digests it may still vouch for
    serial               the list's number
    signers.json         the list itself
--legacy FILE is /etc/auditisa-firm/release-signing.pub, which older scripts read: it gets the first
active signer's key.

The checks are those of addons/ea_platform_admin/services/signers.py (parse): the two must agree.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import sys

SCHEMA = "auditisa-signers-v1"
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
PEM = re.compile(r"^-----BEGIN PUBLIC KEY-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END PUBLIC KEY-----\s*$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


class Refused(Exception):
    pass


def der_of(pem):
    found = PEM.match((pem or "").strip())
    if not found or "PRIVATE" in pem.upper():
        raise Refused("not a public key")
    try:
        der = base64.b64decode("".join(found.group(1).split()), validate=True)
    except ValueError:
        raise Refused("unreadable key") from None
    if len(der) != len(ED25519_SPKI_PREFIX) + 32 or not der.startswith(ED25519_SPKI_PREFIX):
        raise Refused("not an ed25519 key")
    return der


def normalise(pem):
    body = base64.b64encode(der_of(pem)).decode("ascii")
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + "\n-----END PUBLIC KEY-----\n"


def parse(raw):
    try:
        data = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("unreadable list") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise Refused("unknown schema")
    serial = data.get("serial")
    if type(serial) is not int or not 1 <= serial <= 1000000:
        raise Refused("bad number")
    result = {"serial": serial, "signers": [], "retired": []}
    for group in ("signers", "retired"):
        rows = data.get(group, [])
        if not isinstance(rows, list) or len(rows) > 50:
            raise Refused("bad " + group)
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("public_key"), str):
                raise Refused("bad entry")
            pem = normalise(row["public_key"])
            fingerprint = hashlib.sha256(der_of(pem)).hexdigest()
            if row.get("fingerprint") != fingerprint:
                raise Refused("fingerprint does not match its key")
            name, email = row.get("name"), row.get("email")
            if not isinstance(name, str) or not 0 < len(name.strip()) <= 64 or any(ord(c) < 32 for c in name):
                raise Refused("bad name")
            if not isinstance(email, str) or not EMAIL.match(email):
                raise Refused("bad email")
            item = {"fingerprint": fingerprint, "pem": pem}
            if group == "retired":
                digests = row.get("valid_for", [])
                if not isinstance(digests, list) or not all(isinstance(d, str) and HEX64.match(d) for d in digests):
                    raise Refused("bad valid_for")
                item["valid_for"] = sorted(set(digests))
            result[group].append(item)
    if not result["signers"]:
        raise Refused("no active signer")
    seen = [row["fingerprint"] for row in result["signers"] + result["retired"]]
    if len(seen) != len(set(seen)):
        raise Refused("a key is listed twice")
    return result


def serial_of(folder):
    try:
        with open(os.path.join(folder, "serial"), encoding="ascii") as handle:
            value = handle.read(16).strip()
    except (OSError, UnicodeDecodeError):
        return 0
    return int(value) if value.isdigit() else 0


def _write(path, text, mode=0o644):
    with open(path, "w", encoding="ascii") as handle:
        handle.write(text)
    os.chmod(path, mode)


def adopt(raw, folder, legacy=None):
    """True when the list was taken, False when the one in use is as new or newer."""
    trust = parse(raw)
    if trust["serial"] <= serial_of(folder):
        return False
    fresh, old = folder + ".new", folder + ".old"
    shutil.rmtree(fresh, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    os.makedirs(fresh, mode=0o755)
    for row in trust["signers"] + trust["retired"]:
        _write(os.path.join(fresh, row["fingerprint"] + ".pub"), row["pem"])
        if "valid_for" in row:
            _write(os.path.join(fresh, row["fingerprint"] + ".only"), "\n".join(row["valid_for"] or ["none"]) + "\n")
    _write(os.path.join(fresh, "signers.json"), raw.decode("ascii"))
    _write(os.path.join(fresh, "serial"), f"{trust['serial']}\n")
    if os.path.isdir(folder):
        os.rename(folder, old)
    os.rename(fresh, folder)
    shutil.rmtree(old, ignore_errors=True)
    if legacy:
        _write(legacy + ".tmp", trust["signers"][0]["pem"])
        os.replace(legacy + ".tmp", legacy)
    return True


def main(argv):
    if len(argv) >= 2 and argv[0] == "serial":
        print(serial_of(argv[1]))
        return 0
    try:
        if len(argv) == 2 and argv[0] == "check":
            with open(argv[1], "rb") as handle:
                print(parse(handle.read())["serial"])
            return 0
        if len(argv) in (3, 5) and argv[0] == "adopt":
            legacy = argv[4] if len(argv) == 5 and argv[3] == "--legacy" else None
            if len(argv) == 5 and not legacy:
                raise Refused("usage")
            with open(argv[1], "rb") as handle:
                raw = handle.read()
            taken = adopt(raw, argv[2], legacy)
            print(("adopted " if taken else "kept ") + str(serial_of(argv[2])))
            return 0
    except (Refused, OSError) as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    print(__doc__.split("\n\n")[0], file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
