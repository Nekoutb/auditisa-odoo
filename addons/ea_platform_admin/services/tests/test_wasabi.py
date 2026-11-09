"""Wasabi: signatures, names, the two access policies, and every call the console makes. No network."""

import base64
import hashlib
import json
import re
import socket
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from .. import sigv4
from .. import wasabi_policy as names
from ..provider import ProviderError
from ..provider_vultr import HttpResponse
from ..storage_wasabi import WasabiStorage
from ..wasabi_policy import ALLOW, CONSOLE_POLICY, DENY, IMPLICIT_DENY, evaluate, firm_bucket_policy

ROOT = Path(__file__).parents[4]
ACCOUNT = "100000012345"
CONSOLE_KEY = "CONSOLEKEYID00000001"
CONSOLE_SECRET = "console-SECRET-value-that-must-never-leak"
NOW = "20261109T120000Z"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ------------------------------------------------------------------------------ SigV4


def test_header_signature_matches_aws_published_example():
    """AWS's own example: GET iam ListUsers, AKIDEXAMPLE, 2015-08-30 12:36:00 UTC."""
    query = [("Action", "ListUsers"), ("Version", "2010-05-08")]
    headers = sigv4.sign_headers(
        "GET", "https://iam.amazonaws.com/", query,
        {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}, b"",
        "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "us-east-1", "iam", "20150830T123600Z",
    )
    assert headers["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/iam/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date, "
        "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"
    )


def test_presigned_address_matches_aws_published_example():
    """AWS's S3 example: GET /test.txt from examplebucket, 2013-05-24, valid 86400 seconds."""
    url = sigv4.presign_url(
        "https://examplebucket.s3.amazonaws.com/test.txt", "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", "20130524T000000Z", 86400,
    )
    assert url.endswith("X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404")
    assert "X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request" in url


def test_presigned_addresses_last_seven_days_at_most():
    for seconds in (0, sigv4.MAX_PRESIGN_SECONDS + 1):
        with pytest.raises(ValueError):
            sigv4.presign_url("https://h.example/b/k", "A", "S", "eu-central-1", NOW, seconds)


def test_signatures_agree_with_botocore_when_it_is_installed():
    """Not needed by the console. When botocore is at hand (a developer's machine), both must agree."""
    botocore = pytest.importorskip("botocore")
    from botocore.auth import S3SigV4Auth, SigV4Auth, S3SigV4QueryAuth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials
    import datetime
    from unittest import mock

    credentials = Credentials("AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
    fixed = datetime.datetime(2026, 11, 9, 12, 0, 0)
    with mock.patch("botocore.auth.get_current_datetime", return_value=fixed):
        # IAM, a form POST
        body = b"Action=CreateUser&Path=%2Fauditisa%2F&UserName=auditisa-firm-a&Version=2010-05-08"
        request = AWSRequest("POST", "https://iam.wasabisys.com/", data=body,
                             headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})
        SigV4Auth(credentials, "iam", "us-east-1").add_auth(request)
        ours = sigv4.sign_headers("POST", "https://iam.wasabisys.com/", [], {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
                                  body, credentials.access_key, credentials.secret_key, "us-east-1", "iam", NOW)
        assert ours["Authorization"] == request.headers["Authorization"]
        # S3, a bucket policy (path style, a query without value)
        payload = b'{"Version":"2012-10-17"}'
        url = "https://s3.eu-central-1.wasabisys.com/auditisa-fw-a-0123456789ab?policy="
        request = AWSRequest("PUT", url, data=payload, headers={"Content-Type": "application/json"})
        S3SigV4Auth(credentials, "s3", "eu-central-1").add_auth(request)
        ours = sigv4.sign_headers("PUT", url.split("?")[0], [("policy", "")], {"Content-Type": "application/json"}, payload,
                                  credentials.access_key, credentials.secret_key, "eu-central-1", "s3", NOW)
        assert ours["Authorization"] == request.headers["Authorization"]
        # A presigned download
        url = "https://s3.eu-central-1.wasabisys.com/auditisa-releases-abcd1234/0123456789ab.tar.gz"
        request = AWSRequest("GET", url)
        S3SigV4QueryAuth(credentials, "s3", "eu-central-1", expires=21600).add_auth(request)
        theirs = dict(parse_qsl(urlsplit(request.url).query))
        ours = dict(parse_qsl(urlsplit(sigv4.presign_url(url, credentials.access_key, credentials.secret_key,
                                                         "eu-central-1", NOW, 21600)).query))
        assert ours["X-Amz-Signature"] == theirs["X-Amz-Signature"]
    assert botocore


# ------------------------------------------------------------------------------ names


def test_names():
    assert names.firm_user("cabinet-a") == "auditisa-firm-cabinet-a"
    bucket = names.new_firm_bucket("cabinet-a")
    assert re.fullmatch(r"auditisa-fw-cabinet-a-[0-9a-f]{12}", bucket)
    assert names.new_firm_bucket("cabinet-a") != bucket  # random
    longest = names.new_firm_bucket("a" * 32)
    assert len(longest) <= 63 and len(names.firm_user("a" * 32)) <= 64
    assert names.slug_of_label("auditisa-firm-cabinet-a") == "cabinet-a"
    for wrong in ("cabinet-a", "auditisa-firm-", "auditisa-firm-A", "auditisa-firm-a--b", "auditisa-firm-x/../y"):
        with pytest.raises(ValueError):
            names.slug_of_label(wrong)


def test_a_bucket_belongs_to_exactly_one_firm():
    assert names.slug_of_bucket("auditisa-fw-abc-0123456789ab") == "abc"
    assert names.slug_of_bucket("auditisa-fw-abc-def-0123456789ab") == "abc-def"
    for other in ("auditisa-fw-abc", "auditisa-fw-abc-0123456789aZ", "auditisa-fw-abc-0123456789abc",
                  "auditisa-releases-0123456789ab", "family-photos", "auditisa-fw-a--b-0123456789ab"):
        assert names.slug_of_bucket(other) is None, other


# ------------------------------------------------------------------------------ the console's policy


def _fenced_json(text):
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", text, re.S)]


def test_the_policy_the_owner_pastes_is_the_one_in_the_code():
    shipped = json.loads((ROOT / "deploy/control-plane/wasabi-console-policy.json").read_text(encoding="utf-8"))
    assert shipped == CONSOLE_POLICY
    runbook = _fenced_json((ROOT / "docs/runbook/WASABI.md").read_text(encoding="utf-8"))
    assert runbook and all(block == CONSOLE_POLICY for block in runbook)


FIRM_A = f"arn:aws:iam::{ACCOUNT}:user/auditisa/auditisa-firm-cabinet-a"
FIRM_B = f"arn:aws:iam::{ACCOUNT}:user/auditisa/auditisa-firm-cabinet-b"
BUCKET_A = "auditisa-fw-cabinet-a-0123456789ab"
BUCKET_B = "auditisa-fw-cabinet-b-ba9876543210"
RELEASES = "auditisa-releases-k3j4h5g6f7d8"


def s3(bucket, key=None):
    return f"arn:aws:s3:::{bucket}" + (f"/{key}" if key is not None else "")


def user(path_and_name):
    return f"arn:aws:iam::{ACCOUNT}:user/{path_and_name}"


def console(action, resource):
    return evaluate([CONSOLE_POLICY], action, resource)


@pytest.mark.parametrize("action,resource", [
    ("s3:ListAllMyBuckets", "*"),
    ("s3:CreateBucket", s3(BUCKET_A)),
    ("s3:PutBucketPolicy", s3(BUCKET_A)),
    ("s3:ListBucket", s3(BUCKET_A)),
    ("s3:DeleteObject", s3(BUCKET_A, "restic/data/00/x")),
    ("s3:DeleteBucket", s3(BUCKET_A)),
    ("s3:GetObject", s3(RELEASES, "0123456789ab.tar.gz")),
    ("s3:PutObject", s3(RELEASES, "0123456789ab.tar.gz.sig")),
    ("iam:CreateUser", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:CreateAccessKey", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:ListAccessKeys", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:DeleteAccessKey", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:DeleteUser", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:GetUser", user("auditisa-firm-cabinet-a")),
])
def test_the_console_may_do_its_work(action, resource):
    assert console(action, resource) == ALLOW


@pytest.mark.parametrize("action,resource", [
    # the owner's other buckets and users
    ("s3:ListBucket", s3("family-photos")),
    ("s3:GetObject", s3("family-photos", "2026/me.jpg")),
    ("s3:DeleteBucket", s3("family-photos")),
    ("s3:PutBucketPolicy", s3("family-photos")),
    ("iam:DeleteUser", user("owner")),
    ("iam:CreateAccessKey", user("owner")),
    ("iam:CreateUser", user("someone-else")),
    ("iam:CreateUser", user("auditisa/someone-else")),
    # itself: no second key, no more rights
    ("iam:CreateAccessKey", user("auditisa-console")),
    ("iam:DeleteUser", user("auditisa-console")),
    # no action that writes or attaches a policy on any user, nor makes a policy
    ("iam:PutUserPolicy", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:PutUserPolicy", user("auditisa-console")),
    ("iam:AttachUserPolicy", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:AttachUserPolicy", user("auditisa-console")),
    ("iam:CreatePolicy", f"arn:aws:iam::{ACCOUNT}:policy/anything"),
    ("iam:CreatePolicyVersion", f"arn:aws:iam::{ACCOUNT}:policy/auditisa-console-policy"),
    ("iam:AddUserToGroup", f"arn:aws:iam::{ACCOUNT}:group/admins"),
    ("iam:CreateLoginProfile", user("auditisa/auditisa-firm-cabinet-a")),
    ("iam:UpdateUser", user("auditisa/auditisa-firm-cabinet-a")),
    # it never reads a firm's backups, nor deletes a release
    ("s3:GetObject", s3(BUCKET_A, "restic/config")),
    ("s3:PutObject", s3(BUCKET_A, "restic/config")),
    ("s3:DeleteObject", s3(RELEASES, "0123456789ab.tar.gz")),
    ("s3:DeleteBucket", s3(RELEASES)),
    ("s3:PutBucketPolicy", s3(RELEASES)),
    ("s3:PutBucketAcl", s3(BUCKET_A)),
    ("s3:PutBucketVersioning", s3(BUCKET_A)),
])
def test_the_console_may_not_reach_beyond_the_platform(action, resource):
    assert console(action, resource) == IMPLICIT_DENY


def test_the_console_policy_has_no_wildcard_action_and_one_global_resource():
    for statement in CONSOLE_POLICY["Statement"]:
        actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        assert all("*" not in action for action in actions)
        resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
        if resources == ["*"]:
            assert actions == ["s3:ListAllMyBuckets"]
        else:
            assert all(r.startswith(("arn:aws:s3:::auditisa-", "arn:aws:iam::*:user/auditisa")) for r in resources)
        assert statement["Effect"] == "Allow"


# ------------------------------------------------------------------------------ a firm's bucket policy


def test_a_firm_key_opens_its_own_bucket_only():
    policies = [firm_bucket_policy(BUCKET_A, FIRM_A), firm_bucket_policy(BUCKET_B, FIRM_B)]
    for action in ("s3:GetObject", "s3:PutObject", "s3:DeleteObject"):
        assert evaluate(policies, action, s3(BUCKET_A, "restic/data/ab/x"), FIRM_A) == ALLOW
        assert evaluate(policies, action, s3(BUCKET_B, "restic/data/ab/x"), FIRM_A) == IMPLICIT_DENY
        assert evaluate(policies, action, s3(BUCKET_A, "restic/data/ab/x"), FIRM_B) == IMPLICIT_DENY
        assert evaluate(policies, action, s3(BUCKET_A, "x"), "anonymous") == IMPLICIT_DENY
    assert evaluate(policies, "s3:ListBucket", s3(BUCKET_A), FIRM_A) == ALLOW
    assert evaluate(policies, "s3:ListBucket", s3(BUCKET_B), FIRM_A) == IMPLICIT_DENY
    for action in ("s3:DeleteBucket", "s3:PutBucketPolicy", "s3:ListAllMyBuckets", "s3:CreateBucket"):
        assert evaluate(policies, action, s3(BUCKET_A), FIRM_A) == IMPLICIT_DENY
    # Nothing in the releases bucket: the firm downloads with signed addresses.
    assert evaluate(policies, "s3:GetObject", s3(RELEASES, "a.tar.gz"), FIRM_A) == IMPLICIT_DENY


def test_a_bucket_policy_is_only_written_for_its_own_firm():
    with pytest.raises(ValueError):
        firm_bucket_policy(BUCKET_A, FIRM_B)
    with pytest.raises(ValueError):
        firm_bucket_policy("family-photos", FIRM_A)
    with pytest.raises(ValueError):
        firm_bucket_policy(BUCKET_A, "*")
    with pytest.raises(ValueError):
        firm_bucket_policy(BUCKET_A, user("auditisa-console"))
    # firm "cabinet" never gets the bucket of firm "cabinet-a"
    with pytest.raises(ValueError):
        firm_bucket_policy(BUCKET_A, user("auditisa/auditisa-firm-cabinet"))
    assert firm_bucket_policy(BUCKET_A, user("auditisa-firm-cabinet-a"))  # an ARN without its path


def test_the_evaluator_itself():
    deny = {"Statement": [{"Effect": "Deny", "Action": "s3:*", "Resource": "*"}]}
    allow = {"Statement": [{"Effect": "Allow", "Action": "S3:Get*", "Resource": "arn:aws:s3:::b?/*"}]}
    assert evaluate([allow], "s3:GetObject", "arn:aws:s3:::b1/k") == ALLOW
    assert evaluate([allow], "s3:GetObject", "arn:aws:s3:::b12/k") == IMPLICIT_DENY
    assert evaluate([allow, deny], "s3:GetObject", "arn:aws:s3:::b1/k") == DENY


# ------------------------------------------------------------------------------ the calls


class FakeWasabi:
    """A small Wasabi: buckets, objects, users and keys in memory. Records every request."""

    def __init__(self, buckets=(), users=(), objects=None, fail=None):
        self.buckets = {name: {} for name in buckets}
        for name, keys in (objects or {}).items():
            self.buckets[name] = {key: b"x" for key in keys}
        self.users = {name: {"path": "/auditisa/", "keys": []} for name in users}
        self.policies = {}
        self.fail = dict(fail or {})
        self.requests = []
        self.counter = 0

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, dict(headers), body))
        parts = urlsplit(url)
        assert parts.scheme == "https"
        assert headers["Authorization"].startswith(f"AWS4-HMAC-SHA256 Credential={CONSOLE_KEY}/")
        if parts.netloc == "iam.wasabisys.com":
            params = dict(parse_qsl(body.decode("ascii"), keep_blank_values=True))
            return self._iam(params)
        assert parts.netloc == "s3.eu-central-1.wasabisys.com"
        assert headers["x-amz-content-sha256"] == hashlib.sha256(body or b"").hexdigest()
        return self._s3(method, parts.path.strip("/"), dict(parse_qsl(parts.query, keep_blank_values=True)), body)

    def _error(self, status, code):
        return HttpResponse(status, f"<Error><Code>{code}</Code><Message>{CONSOLE_SECRET}</Message></Error>".encode())

    def _iam(self, params):
        action, name = params["Action"], params.get("UserName", "")
        if action in self.fail:
            return self._error(*self.fail.pop(action))
        user = self.users.get(name)
        arn = f"arn:aws:iam::{ACCOUNT}:user/auditisa/{name}"
        if action == "GetUser":
            if not user:
                return self._error(404, "NoSuchEntity")
            return HttpResponse(200, f"<GetUserResponse><GetUserResult><User><Arn>{arn}</Arn></User></GetUserResult></GetUserResponse>".encode())
        if action == "CreateUser":
            assert params["Path"] == "/auditisa/"
            self.users[name] = {"path": params["Path"], "keys": []}
            return HttpResponse(200, f"<CreateUserResponse><CreateUserResult><User><Arn>{arn}</Arn></User></CreateUserResult></CreateUserResponse>".encode())
        if action == "ListAccessKeys":
            if not user:
                return self._error(404, "NoSuchEntity")
            members = "".join(f"<member><AccessKeyId>{key}</AccessKeyId></member>" for key, _secret in user["keys"])
            return HttpResponse(200, f"<ListAccessKeysResponse><ListAccessKeysResult><AccessKeyMetadata>{members}</AccessKeyMetadata></ListAccessKeysResult></ListAccessKeysResponse>".encode())
        if action == "DeleteAccessKey":
            user["keys"] = [k for k in user["keys"] if k[0] != params["AccessKeyId"]]
            return HttpResponse(200, b"<DeleteAccessKeyResponse/>")
        if action == "CreateAccessKey":
            self.counter += 1
            key = (f"FIRMKEY{self.counter:013d}", f"firm-secret-{self.counter}")
            user["keys"].append(key)
            return HttpResponse(200, (
                "<CreateAccessKeyResponse><CreateAccessKeyResult><AccessKey>"
                f"<AccessKeyId>{key[0]}</AccessKeyId><SecretAccessKey>{key[1]}</SecretAccessKey>"
                "</AccessKey></CreateAccessKeyResult></CreateAccessKeyResponse>").encode())
        if action == "DeleteUser":
            if not user:
                return self._error(404, "NoSuchEntity")
            if user["keys"]:
                return self._error(409, "DeleteConflict")
            del self.users[name]
            return HttpResponse(200, b"<DeleteUserResponse/>")
        raise AssertionError(f"unexpected IAM action {action}")

    def _s3(self, method, bucket, query, body):
        call = (method, "policy" if "policy" in query else "delete" if "delete" in query else "")
        if call in self.fail:
            return self._error(*self.fail.pop(call))
        if not bucket and method == "GET":
            names_xml = "".join(f"<Bucket><Name>{name}</Name></Bucket>" for name in self.buckets)
            return HttpResponse(200, f"<ListAllMyBucketsResult><Buckets>{names_xml}</Buckets></ListAllMyBucketsResult>".encode())
        if method == "PUT" and "policy" in query:
            assert bucket in self.buckets
            self.policies[bucket] = json.loads(body)
            return HttpResponse(204)
        if method == "PUT":
            if bucket in self.buckets:
                return self._error(409, "BucketAlreadyOwnedByYou")
            self.buckets[bucket] = {}
            return HttpResponse(200)
        if method == "GET" and query.get("list-type") == "2":
            if bucket not in self.buckets:
                return self._error(404, "NoSuchBucket")
            limit = int(query["max-keys"])
            keys = sorted(self.buckets[bucket])[:limit]
            contents = "".join(f"<Contents><Key>{key}</Key></Contents>" for key in keys)
            return HttpResponse(200, f"<ListBucketResult>{contents}</ListBucketResult>".encode())
        if method == "POST" and "delete" in query:
            expected = base64.b64encode(hashlib.md5(body).digest()).decode()  # noqa: S324
            assert self.requests[-1][2]["Content-MD5"] == expected
            for element in ET.fromstring(body).iter("Key"):
                self.buckets[bucket].pop(element.text, None)
            return HttpResponse(200, b"<DeleteResult/>")
        if method == "DELETE":
            if bucket not in self.buckets:
                return self._error(404, "NoSuchBucket")
            assert not self.buckets[bucket], "a bucket is emptied before it is deleted"
            del self.buckets[bucket]
            self.policies.pop(bucket, None)
            return HttpResponse(204)
        raise AssertionError(f"unexpected S3 call {method} {bucket} {query}")


def storage(fake, **kwargs):
    return WasabiStorage(CONSOLE_KEY, CONSOLE_SECRET, "eu-central-1", releases_bucket=RELEASES, transport=fake,
                         clock=lambda: NOW, new_bucket=kwargs.pop("new_bucket", lambda slug: f"auditisa-fw-{slug}-0123456789ab"),
                         **kwargs)


def test_onboarding_makes_a_bucket_a_user_its_bucket_policy_and_one_key():
    fake = FakeWasabi(buckets=["family-photos"])
    wasabi = storage(fake)
    label = "auditisa-firm-cabinet-a"
    assert wasabi.find_storage(label) is None
    bucket = wasabi.create_storage(label, "cdg")
    assert bucket == BUCKET_A
    create = [r for r in fake.requests if r[0] == "PUT" and r[1].endswith(BUCKET_A)][0]
    assert b"<LocationConstraint>eu-central-1</LocationConstraint>" in create[3]
    assert wasabi.find_storage(label) == bucket
    credentials = wasabi.storage_credentials(bucket)
    assert (credentials.endpoint, credentials.bucket, credentials.region) == ("s3.eu-central-1.wasabisys.com", bucket, "eu-central-1")
    assert credentials.access_key == "FIRMKEY0000000000001"
    assert fake.users["auditisa-firm-cabinet-a"]["keys"] == [("FIRMKEY0000000000001", "firm-secret-1")]
    assert fake.policies[bucket] == firm_bucket_policy(bucket, FIRM_A)
    assert "family-photos" not in fake.policies
    assert "firm-secret-1" not in repr(credentials)


def test_getting_the_key_again_revokes_the_one_never_delivered():
    fake = FakeWasabi(buckets=[BUCKET_A])
    wasabi = storage(fake)
    first = wasabi.storage_credentials(BUCKET_A)
    second = wasabi.storage_credentials(BUCKET_A)
    assert first.access_key != second.access_key
    assert [k for k, _s in fake.users["auditisa-firm-cabinet-a"]["keys"]] == [second.access_key]
    assert len([r for r in fake.requests if b"Action=CreateUser" in (r[3] or b"")]) == 1


def test_find_storage_is_exact_and_refuses_ambiguity():
    fake = FakeWasabi(buckets=["auditisa-fw-cabinet-a-b-0123456789ab", "family-photos", "auditisa-fw-cabinet-0123456789ab"])
    wasabi = storage(fake)
    assert wasabi.find_storage("auditisa-firm-cabinet-a") is None
    assert wasabi.find_storage("auditisa-firm-cabinet") == "auditisa-fw-cabinet-0123456789ab"
    fake.buckets["auditisa-fw-cabinet-ffffffffffff"] = {}
    with pytest.raises(ProviderError):
        wasabi.find_storage("auditisa-firm-cabinet")
    with pytest.raises(ProviderError):
        wasabi.find_storage("family-photos")


def test_deletion_removes_keys_user_every_backup_then_the_bucket():
    many = [f"restic/data/{i:04d}" for i in range(2500)]
    fake = FakeWasabi(buckets=["family-photos"], objects={BUCKET_A: many, "family-photos": ["me.jpg"]})
    wasabi = storage(fake)
    wasabi.storage_credentials(BUCKET_A)
    wasabi.delete_storage(BUCKET_A)
    assert "auditisa-firm-cabinet-a" not in fake.users
    assert BUCKET_A not in fake.buckets
    assert fake.buckets["family-photos"] == {"me.jpg": b"x"}
    batches = [r for r in fake.requests if r[0] == "POST" and "delete=" in r[1]]
    assert len(batches) == 3  # 1000 + 1000 + 500
    # Again: nothing left, nothing fails.
    wasabi.delete_storage(BUCKET_A)


def test_deletion_refuses_anything_but_a_firms_bucket():
    fake = FakeWasabi(buckets=["family-photos"])
    for name in ("family-photos", RELEASES, "auditisa-fw-x"):
        with pytest.raises(ProviderError):
            storage(fake).delete_storage(name)
    assert fake.requests == []


@pytest.mark.parametrize("failure,retryable", [
    ((503, "ServiceUnavailable"), True),
    ((500, "InternalError"), True),
    ((429, "SlowDown"), True),
    ((400, "MalformedPolicy"), True),  # a user just made, not yet known to S3
    ((403, "AccessDenied"), False),
    ((400, "InvalidArgument"), False),
])
def test_errors_say_if_a_retry_may_help_and_never_repeat_the_answer(failure, retryable):
    fake = FakeWasabi(buckets=[BUCKET_A], fail={("PUT", "policy"): failure})
    with pytest.raises(ProviderError) as caught:
        storage(fake).storage_credentials(BUCKET_A)
    assert caught.value.retryable is retryable
    assert CONSOLE_SECRET not in str(caught.value)
    assert not fake.users["auditisa-firm-cabinet-a"]["keys"], "no key is made before the bucket policy holds"


def test_the_console_secret_is_never_sent_nor_shown():
    fake = FakeWasabi()
    wasabi = storage(fake)
    bucket = wasabi.create_storage("auditisa-firm-cabinet-a", "cdg")
    wasabi.storage_credentials(bucket)
    wasabi.release_url("0123456789ab.tar.gz", 3600)
    wasabi.delete_storage(bucket)
    for method, url, headers, body in fake.requests:
        assert CONSOLE_SECRET not in url + json.dumps(headers) + (body or b"").decode("utf-8", "replace")
    assert CONSOLE_SECRET not in repr(wasabi) and CONSOLE_SECRET not in str(vars(wasabi))
    assert "CONSOLEKEY" not in repr(wasabi)


def test_release_addresses_are_signed_short_and_for_the_releases_bucket():
    wasabi = storage(FakeWasabi())
    url = wasabi.release_url("0123456789ab.tar.gz", 6 * 3600)
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    assert parts.netloc == "s3.eu-central-1.wasabisys.com"
    assert parts.path == f"/{RELEASES}/0123456789ab.tar.gz"
    assert query["X-Amz-Expires"] == "21600"
    assert query["X-Amz-Credential"].startswith(f"{CONSOLE_KEY}/20261109/eu-central-1/s3/")
    assert wasabi.releases_base_url() == f"https://s3.eu-central-1.wasabisys.com/{RELEASES}"
    with pytest.raises(ProviderError):
        WasabiStorage("k", "s", "eu-central-1", transport=FakeWasabi()).release_url("x", 60)


def test_settings_are_checked_when_the_storage_is_built():
    for kwargs in ({"region": "Amsterdam"}, {"region": "eu-central-1", "endpoint": "https://x/y"},
                   {"region": "eu-central-1", "releases_bucket": "family-photos"}):
        with pytest.raises(ProviderError):
            WasabiStorage("k", "s", transport=FakeWasabi(), **kwargs)
    assert WasabiStorage("k", "s", "us-east-1", transport=FakeWasabi()).endpoint == "s3.us-east-1.wasabisys.com"


def test_us_east_1_buckets_are_made_without_a_location():
    fake = FakeWasabi()
    wasabi = WasabiStorage(CONSOLE_KEY, CONSOLE_SECRET, "us-east-1", transport=fake, clock=lambda: NOW,
                           new_bucket=lambda slug: f"auditisa-fw-{slug}-0123456789ab")
    fake_host = "s3.us-east-1.wasabisys.com"
    fake.__class__ = type("FakeUsEast", (FakeWasabi,), {
        "__call__": lambda self, m, u, h, b: (self.requests.append((m, u, dict(h), b)), HttpResponse(200))[1],
    })
    wasabi.create_storage("auditisa-firm-cabinet-a", "cdg")
    method, url, _headers, body = fake.requests[-1]
    assert (method, urlsplit(url).netloc, body) == ("PUT", fake_host, b"")
