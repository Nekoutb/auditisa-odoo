"""Wasabi object storage behind the storage methods of provider.ServerProvider. Pure.

NEVER RUN AGAINST THE REAL SERVICE during this build: the tests inject a fake transport and check
the requests. Written from AWS's S3 and IAM API references, which Wasabi follows; what only a real
key can confirm is listed in docs/runbook/WASABI.md.

Per firm (names and rules in wasabi_policy.py): a bucket, a user with no policy of its own, a
bucket policy that opens that bucket to that user only, and one access key, created when the
server is created and handed to it in its first-boot text, never kept here.

The console's own key and secret are read from root-only files (systemd LoadCredential) and held by
nothing but this object. They never appear in an error, a log or a repr.
"""

import base64
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote
from xml.sax.saxutils import escape

from . import sigv4
from . import wasabi_policy as names
from .messages import _
from .provider import ProviderError, StorageCredentials
from .provider_vultr import UrllibTransport

IAM_ENDPOINT = "iam.wasabisys.com"
IAM_REGION = "us-east-1"  # Wasabi's IAM is global and signs as us-east-1
IAM_VERSION = "2010-05-08"
DELETE_BATCH = 1000  # S3's limit per DeleteObjects call

# Errors that can pass by themselves. MalformedPolicy: a user just made may not be known yet to
# the bucket-policy check (IAM is eventually consistent); the step is tried again a little later.
_RETRYABLE_CODES = {"SlowDown", "ServiceUnavailable", "InternalError", "RequestTimeout", "MalformedPolicy", "OperationAborted"}


def _amz_now():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _find_all(root, name):
    return [element for element in root.iter() if _local(element.tag) == name]


def _text(root, name):
    found = _find_all(root, name)
    return (found[0].text or "").strip() if found else ""


def _xml(body):
    try:
        return ET.fromstring(body) if body else None
    except ET.ParseError:
        return None


class _Keys:
    """The console's key and secret. Its repr, and so any error or log that shows it, holds neither."""

    __slots__ = ("access", "secret")

    def __init__(self, access, secret):
        self.access = access
        self.secret = secret

    def __repr__(self):
        return "<Wasabi console key>"


class WasabiStorage:
    """The storage half of the provider. `transport` is provider_vultr.UrllibTransport in real use."""

    name = "wasabi"

    def __init__(self, access_key, secret_key, region, endpoint=None, releases_bucket=None,
                 transport=None, clock=None, new_bucket=None):
        if not names.REGION_RE.match(region or ""):
            raise ProviderError(_("Invalid Wasabi region."))
        endpoint = endpoint or names.default_endpoint(region)
        if not names.ENDPOINT_RE.match(endpoint):
            raise ProviderError(_("Invalid Wasabi endpoint."))
        if releases_bucket and not names.RELEASES_BUCKET_RE.match(releases_bucket):
            raise ProviderError(_("The releases bucket must be named auditisa-releases-..."))
        self._keys = _Keys(access_key, secret_key)
        self.region = region
        self.endpoint = endpoint
        self.releases_bucket = releases_bucket or ""
        self._transport = transport or UrllibTransport()
        self._clock = clock or _amz_now
        self._new_bucket = new_bucket or names.new_firm_bucket

    def __repr__(self):
        return f"<Wasabi storage {self.region}>"

    # ------------------------------------------------------------------ signed calls

    def _send(self, method, host, path, query, body, headers, region, service, what):
        url = f"https://{host}{path}"
        query_text = sigv4.canonical_query(query)
        signed = sigv4.sign_headers(
            method, url, query, headers, body, self._keys.access, self._keys.secret, region, service, self._clock(),
        )
        response = self._transport(method, url + (f"?{query_text}" if query_text else ""), signed, body)
        root = _xml(response.body)
        code = _text(root, "Code") if root is not None else ""
        if response.status == 429 or response.status >= 500 or code in _RETRYABLE_CODES:
            raise ProviderError(
                _("Wasabi: temporary error %(status)s on %(call)s.", status=response.status, call=what), retryable=True,
            )
        return response.status, code, root

    def _refused(self, status, code, what):
        # Only the error code: the answer itself could repeat what was sent.
        return ProviderError(_("Wasabi refused %(call)s (%(status)s %(code)s).", call=what, status=status, code=code or "-"))

    def _s3(self, method, bucket="", query=(), body=b"", headers=None, what=""):
        path = "/" + quote(bucket, safe="") if bucket else "/"
        return self._send(method, self.endpoint, path, list(query), body, dict(headers or {}), self.region, "s3", what)

    def _iam(self, action, **params):
        form = [("Action", action), ("Version", IAM_VERSION)] + sorted(params.items())
        body = sigv4.canonical_query(form).encode("ascii")
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        status, code, root = self._send("POST", IAM_ENDPOINT, "/", [], body, headers, IAM_REGION, "iam", f"iam:{action}")
        return status, code, root

    # ------------------------------------------------------------------ buckets

    def _bucket_names(self):
        status, code, root = self._s3("GET", what="s3:ListBuckets")
        if status != 200 or root is None:
            raise self._refused(status, code, "s3:ListBuckets")
        return [(_text(bucket, "Name")) for bucket in _find_all(root, "Bucket")]

    def find_storage(self, label):
        slug = self._slug(label)
        found = sorted(name for name in self._bucket_names() if names.slug_of_bucket(name) == slug)
        if len(found) > 1:
            raise ProviderError(_("Several Wasabi buckets for this firm: %(names)s", names=", ".join(found)))
        return found[0] if found else None

    def create_storage(self, label, region=None):
        """`region` is the server's (Vultr's); the bucket goes to the Wasabi region of the settings."""
        bucket = self._new_bucket(self._slug(label))
        body = b""
        if self.region != "us-east-1":
            body = (
                "<CreateBucketConfiguration xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
                f"<LocationConstraint>{self.region}</LocationConstraint></CreateBucketConfiguration>"
            ).encode("ascii")
        status, code, _root = self._s3("PUT", bucket, body=body, what="s3:CreateBucket")
        if status != 200 and code != "BucketAlreadyOwnedByYou":
            raise self._refused(status, code, "s3:CreateBucket")
        return bucket

    def _put_bucket_policy(self, bucket, user_arn):
        body = json.dumps(names.firm_bucket_policy(bucket, user_arn), separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-MD5": base64.b64encode(hashlib.md5(body).digest()).decode("ascii")}  # noqa: S324  required by S3, not a security use
        status, code, _root = self._s3("PUT", bucket, query=[("policy", "")], body=body, headers=headers, what="s3:PutBucketPolicy")
        if status not in (200, 204):
            raise self._refused(status, code, "s3:PutBucketPolicy")

    def _empty_bucket(self, bucket):
        """Deletes every object, a thousand per call. Returns False if the bucket is not there."""
        while True:
            status, code, root = self._s3("GET", bucket, query=[("list-type", "2"), ("max-keys", str(DELETE_BATCH))], what="s3:ListObjectsV2")
            if status == 404 or code == "NoSuchBucket":
                return False
            if status != 200 or root is None:
                raise self._refused(status, code, "s3:ListObjectsV2")
            keys = [_text(item, "Key") for item in _find_all(root, "Contents")]
            if not keys:
                return True
            body = (
                "<Delete><Quiet>true</Quiet>"
                + "".join(f"<Object><Key>{escape(key)}</Key></Object>" for key in keys)
                + "</Delete>"
            ).encode("utf-8")
            headers = {"Content-Type": "application/xml", "Content-MD5": base64.b64encode(hashlib.md5(body).digest()).decode("ascii")}  # noqa: S324
            status, code, root = self._s3("POST", bucket, query=[("delete", "")], body=body, headers=headers, what="s3:DeleteObjects")
            if status != 200 or (root is not None and _find_all(root, "Error")):
                raise self._refused(status, code or (_text(root, "Code") if root is not None else ""), "s3:DeleteObjects")

    # ------------------------------------------------------------------ the firm's user and key

    def _user_arn(self, user):
        status, code, root = self._iam("GetUser", UserName=user)
        if status == 404 or code == "NoSuchEntity":
            return None
        if status != 200 or root is None:
            raise self._refused(status, code, "iam:GetUser")
        return _text(root, "Arn")

    def _ensure_user(self, user):
        arn = self._user_arn(user)
        if arn:
            return arn
        status, code, root = self._iam("CreateUser", UserName=user, Path=names.IAM_PATH)
        if code == "EntityAlreadyExists":
            return self._user_arn(user)
        if status != 200 or root is None:
            raise self._refused(status, code, "iam:CreateUser")
        return _text(root, "Arn")

    def _delete_keys(self, user):
        status, code, root = self._iam("ListAccessKeys", UserName=user)
        if status == 404 or code == "NoSuchEntity":
            return
        if status != 200 or root is None:
            raise self._refused(status, code, "iam:ListAccessKeys")
        for key_id in [_text(item, "AccessKeyId") for item in _find_all(root, "member")]:
            if not key_id:
                continue
            status, code, _root = self._iam("DeleteAccessKey", UserName=user, AccessKeyId=key_id)
            if status != 200 and code != "NoSuchEntity":
                raise self._refused(status, code, "iam:DeleteAccessKey")

    def storage_credentials(self, storage_id):
        """A new key for the firm's user, every earlier one revoked. Read once, passed on, forgotten.

        Safe to call again: the user and the bucket policy are made only if missing (the policy is
        simply written again), and a key never delivered is replaced.
        """
        slug = names.slug_of_bucket(storage_id)
        if not slug:
            raise ProviderError(_("Not a firm's bucket: %(id)s", id=storage_id))
        user = names.firm_user(slug)
        arn = self._ensure_user(user)
        if not arn:
            raise ProviderError(_("Wasabi did not give the user's identity yet."), retryable=True)
        self._put_bucket_policy(storage_id, arn)
        self._delete_keys(user)
        status, code, root = self._iam("CreateAccessKey", UserName=user)
        if status != 200 or root is None:
            raise self._refused(status, code, "iam:CreateAccessKey")
        access_key, secret_key = _text(root, "AccessKeyId"), _text(root, "SecretAccessKey")
        if not access_key or not secret_key:
            raise ProviderError(_("Wasabi gave no key."))
        return StorageCredentials(
            endpoint=self.endpoint, bucket=storage_id, access_key=access_key, secret_key=secret_key, region=self.region,
        )

    def delete_storage(self, storage_id):
        """The key, the user, every object (all the backups), then the bucket. Safe to call again."""
        slug = names.slug_of_bucket(storage_id)
        if not slug:
            raise ProviderError(_("Not a firm's bucket: %(id)s", id=storage_id))
        user = names.firm_user(slug)
        self._delete_keys(user)
        status, code, _root = self._iam("DeleteUser", UserName=user)
        if status != 200 and status != 404 and code != "NoSuchEntity":
            raise self._refused(status, code, "iam:DeleteUser")
        if not self._empty_bucket(storage_id):
            return
        status, code, _root = self._s3("DELETE", storage_id, what="s3:DeleteBucket")
        if status not in (200, 204, 404) and code != "NoSuchBucket":
            raise self._refused(status, code, "s3:DeleteBucket")

    # ------------------------------------------------------------------ releases

    def release_url(self, filename, expires):
        """A download address for one file of the releases bucket, valid `expires` seconds."""
        if not self.releases_bucket:
            raise ProviderError(_("No releases bucket set."))
        url = f"https://{self.endpoint}/{self.releases_bucket}/{quote(filename, safe='')}"
        return sigv4.presign_url(url, self._keys.access, self._keys.secret, self.region, self._clock(), expires)

    def releases_base_url(self):
        return f"https://{self.endpoint}/{self.releases_bucket}" if self.releases_bucket else ""

    @staticmethod
    def _slug(label):
        try:
            return names.slug_of_label(label)
        except ValueError:
            raise ProviderError(_("Invalid storage label: %(label)s", label=label)) from None
