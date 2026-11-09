"""A firm's own list of trusted signers: what it accepts, and how (only) a signed release changes it.

Runs the real firm-lib.sh and practice-lib.sh functions with bash and openssl, in a folder (FIRM_PREFIX,
PRACTICE_PREFIX), and release_trust.py with this Python. Also checks that the firm side reads a list
exactly as the console writes it.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIRM = HERE.parent
ROOT = FIRM.parents[1]
sys.path.insert(0, str(FIRM))

import release_trust  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("openssl") or not shutil.which("bash") or os.name == "nt",
                                reason="needs bash and openssl (Linux)")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


def new_key(folder, name):
    private = folder / f"{name}.pem"
    run("openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private))
    pem = run("openssl", "pkey", "-in", str(private), "-pubout")
    return private, pem


def fingerprint(pem):
    body = "".join(line for line in pem.strip().splitlines() if "-----" not in line)
    return hashlib.sha256(base64.b64decode(body)).hexdigest()


def sign(private, path):
    run("openssl", "pkeyutl", "-sign", "-inkey", str(private), "-rawin", "-in", str(path), "-out", f"{path}.sig")
    return Path(f"{path}.sig")


def document(serial, active, retired=()):
    def row(name, pem, digests=None):
        item = {"name": name, "email": f"{name.lower()}@example.com", "fingerprint": fingerprint(pem), "public_key": pem}
        if digests is not None:
            item["valid_for"] = sorted(digests)
        return item
    body = {"schema": "auditisa-signers-v1", "serial": serial,
            "signers": [row(n, p) for n, p in active], "retired": [row(n, p, d) for n, p, d in retired]}
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("ascii")


@pytest.fixture
def firm(tmp_path):
    """A firm's /etc in a folder, a list holding Owner only (number 1), and three keys."""
    keys = tmp_path / "keys"
    keys.mkdir()
    owner, owner_pem = new_key(keys, "owner")
    marie, marie_pem = new_key(keys, "marie")
    mallory, mallory_pem = new_key(keys, "mallory")
    prefix = tmp_path / "root"
    etc = prefix / "etc/auditisa-firm"
    (prefix / "var/lib/auditisa-firm/status").mkdir(parents=True)
    etc.mkdir(parents=True)
    raw = document(1, [("Owner", owner_pem)])
    (tmp_path / "first.json").write_bytes(raw)
    assert release_trust.adopt(raw, str(etc / "trusted-signers"), str(etc / "release-signing.pub"))
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(os.urandom(4096))
    return {
        "tmp": tmp_path, "prefix": prefix, "etc": etc, "bundle": bundle,
        "digest": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "owner": (owner, owner_pem), "marie": (marie, marie_pem), "mallory": (mallory, mallory_pem),
    }


def firm_lib(f, script):
    env = dict(os.environ, FIRM_PREFIX=str(f["prefix"]), TRUST_PY=sys.executable, ODOO_PY=sys.executable)
    lib = FIRM / "firm-lib.sh"
    return subprocess.run(["bash", "-c", f'set -euo pipefail; . "{lib}"; {script}'], env=env, capture_output=True, text=True)


def verify(f, signature, digest=None):
    result = firm_lib(f, f'verify_bundle "{f["bundle"]}" "{signature}" "{digest or f["digest"]}" && echo "OK $SIGNED_BY"')
    return result.stdout.strip()


def release_dir(f, name, raw):
    """A release this firm has verified and unpacked, carrying the list `raw`."""
    folder = f["tmp"] / "releases" / name
    (folder / "deploy/trust").mkdir(parents=True)
    (folder / "deploy/firm").mkdir(parents=True)
    (folder / "deploy/trust/signers.json").write_bytes(raw)
    shutil.copy(FIRM / "release_trust.py", folder / "deploy/firm/release_trust.py")
    return folder


def test_the_firm_accepts_a_trusted_signer_and_refuses_an_unknown_one(firm):
    owner, _ = firm["owner"]
    mallory, _ = firm["mallory"]
    assert verify(firm, sign(owner, firm["bundle"])) == f"OK {fingerprint(firm['owner'][1])}"
    assert verify(firm, sign(mallory, firm["bundle"])) == ""
    # The digest is checked first, whoever signed.
    assert verify(firm, sign(owner, firm["bundle"]), digest="0" * 64) == ""


def test_the_firm_adopts_a_new_list_only_from_a_release_and_only_if_newer(firm):
    marie, marie_pem = firm["marie"]
    owner_pem = firm["owner"][1]
    signature = sign(marie, firm["bundle"])
    assert verify(firm, signature) == ""
    # A release carrying list number 2 (Owner and Marie), which the firm verified with Owner's key.
    newer = release_dir(firm, "r2", document(2, [("Owner", owner_pem), ("Marie", marie_pem)]))
    result = firm_lib(firm, f'adopt_trust "{newer}"; cat "$FIRM_STATUS/signers_serial"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("2")
    assert verify(firm, signature) == f"OK {fingerprint(marie_pem)}"
    # An older release, installed again, does not bring an older list back.
    older = release_dir(firm, "r1", document(1, [("Owner", owner_pem)]))
    firm_lib(firm, f'adopt_trust "{older}"')
    assert release_trust.serial_of(str(firm["etc"] / "trusted-signers")) == 2
    assert verify(firm, signature) == f"OK {fingerprint(marie_pem)}"


def test_a_list_that_does_not_hold_is_refused_and_the_list_in_use_stays(firm):
    _mallory, mallory_pem = firm["mallory"]
    body = json.loads(document(5, [("Mallory", mallory_pem)]))
    body["signers"][0]["fingerprint"] = "0" * 64
    bad = release_dir(firm, "bad", (json.dumps(body) + "\n").encode())
    result = firm_lib(firm, f'adopt_trust "{bad}"')
    assert result.returncode == 0
    assert "refused" in result.stderr
    assert release_trust.serial_of(str(firm["etc"] / "trusted-signers")) == 1
    assert verify(firm, sign(firm["mallory"][0], firm["bundle"])) == ""


def test_a_removed_signer_is_refused_except_for_what_they_signed_while_trusted(firm):
    owner, owner_pem = firm["owner"]
    marie, marie_pem = firm["marie"]
    old_digest = firm["digest"]
    raw = document(3, [("Marie", marie_pem)], [("Owner", owner_pem, [old_digest])])
    firm_lib(firm, f'adopt_trust "{release_dir(firm, "r3", raw)}"')
    # What Owner signed while trusted stays valid...
    assert verify(firm, sign(owner, firm["bundle"])) == f"OK {fingerprint(owner_pem)}"
    # ...anything new Owner signs is refused.
    firm["bundle"].write_bytes(os.urandom(4096))
    digest = hashlib.sha256(firm["bundle"].read_bytes()).hexdigest()
    assert verify(firm, sign(owner, firm["bundle"]), digest) == ""
    assert verify(firm, sign(marie, firm["bundle"]), digest) == f"OK {fingerprint(marie_pem)}"
    # The file older scripts read now holds the first active signer.
    assert (firm["etc"] / "release-signing.pub").read_text().strip() == marie_pem.strip()


def test_a_server_from_before_the_list_still_checks_the_one_key(firm):
    shutil.rmtree(firm["etc"] / "trusted-signers")
    (firm["etc"] / "release-signing.pub").write_text(firm["owner"][1])
    assert verify(firm, sign(firm["owner"][0], firm["bundle"])) == "OK release-signing"
    assert verify(firm, sign(firm["marie"][0], firm["bundle"])) == ""


def test_the_firm_reads_a_list_exactly_as_the_console_writes_it(firm):
    sys.path.insert(0, str(ROOT))
    import conftest  # noqa: F401  (registers the addons as packages, without Odoo)
    from ea_platform_admin.services import signers as console
    raw = console.document(4, [{"name": "Owner", "email": "contact@cm-ea.com", "pem": firm["owner"][1]}],
                           [{"name": "Old", "email": "old@example.com", "pem": firm["mallory"][1], "valid_for": ["a" * 64]}])
    parsed = release_trust.parse(raw)
    assert parsed["serial"] == 4
    assert parsed["signers"][0]["fingerprint"] == console.fingerprint(firm["owner"][1])
    assert parsed["retired"][0]["valid_for"] == ["a" * 64]
    repository = (ROOT / "deploy/trust/signers.json").read_bytes()
    assert release_trust.parse(repository)["serial"] == console.parse(repository)["serial"]


def test_the_practice_computer_follows_the_same_rule(firm, tmp_path):
    prefix = tmp_path / "practice"
    etc = prefix / "etc/auditisa-practice"
    (prefix / "var/lib/auditisa-practice/status").mkdir(parents=True)
    etc.mkdir(parents=True)
    owner, owner_pem = firm["owner"]
    marie, marie_pem = firm["marie"]
    release_trust.adopt(document(1, [("Owner", owner_pem)]), str(etc / "trusted-signers"))
    lib = ROOT / "deploy/practice/practice-lib.sh"
    env = dict(os.environ, PRACTICE_PREFIX=str(prefix), ODOO_PY=sys.executable)

    def holds(private):
        signature = sign(private, firm["bundle"])
        script = f'. "{lib}"; practice_signature_holds "{firm["bundle"]}" "{signature}" "{firm["digest"]}" && echo yes'
        return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True).stdout.strip()

    assert holds(owner) == "yes"
    assert holds(marie) == ""
    newer = release_dir(firm, "p2", document(2, [("Owner", owner_pem), ("Marie", marie_pem)]))
    subprocess.run(["bash", "-c", f'. "{lib}"; practice_adopt_trust "{newer}"'], env=env, check=True, capture_output=True)
    assert holds(marie) == "yes"
    assert holds(firm["mallory"][0]) == ""


def test_the_update_scripts_use_the_list():
    update = (FIRM / "firm-update.sh").read_text(encoding="utf-8")
    apply = (FIRM / "firm-apply-desired.sh").read_text(encoding="utf-8")
    practice = (ROOT / "deploy/practice/practice-update.sh").read_text(encoding="utf-8")
    assert "verify_bundle" in update and 'adopt_trust "$TARGET"' in update
    assert update.index("verify_bundle") < update.index('adopt_trust "$TARGET"')
    assert 'adopt_trust "$(readlink -f "$CURRENT_LINK")"' in apply
    assert "practice_signature_holds" in practice and 'practice_adopt_trust "$TARGET"' in practice
    assert "release-signing.pub" not in practice.split("practice_signature_holds")[0].split("unpack()")[1]
