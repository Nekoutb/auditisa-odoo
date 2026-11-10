"""Names and access rules of everything the console makes at Wasabi. Pure.

One Wasabi account. The console signs in as one IAM user, `auditisa-console`, whose policy is
CONSOLE_POLICY below (the owner pastes it once: docs/runbook/WASABI.md). Per firm the console makes:

  - a bucket   auditisa-fw-<slug>-<12 hex>       (random, so the name cannot be guessed)
  - a user     /auditisa/auditisa-firm-<slug>    (no policy of its own, one access key)
  - the bucket's policy, firm_bucket_policy(): that user, and only that user, may list, read and
    write that bucket. Nothing else names the user, so its key opens that one bucket.

Why a bucket policy, not a policy on the user: a console allowed to write policies on users could
write "everything" on a user it made, take that user's key, and so reach every bucket of the
account. CONSOLE_POLICY lets the console write policies only on buckets named auditisa-fw-*, and a
bucket policy can only open its own bucket: a stolen console key reaches the platform's buckets and
users and nothing else of the owner's.

Releases: one private bucket, auditisa-releases-<random>, made by the owner. Firms hold no key to
it. The console signs a short-lived address for each file a firm or the practice computer must
fetch (sigv4.presign_url); the SHA-256 the console sends with it is what the server checks.

`evaluate` is a small IAM policy evaluator (Allow, explicit Deny, wildcards in actions, resources and
principals) with which the tests prove these properties offline. It is not Wasabi's engine: what
only a real key can confirm is listed in docs/runbook/WASABI.md.
"""

import re
import secrets

IAM_PATH = "/auditisa/"
FIRM_USER_PREFIX = "auditisa-firm-"
FIRM_BUCKET_PREFIX = "auditisa-fw-"
RELEASES_BUCKET_PREFIX = "auditisa-releases-"
CONSOLE_USER = "auditisa-console"
CONSOLE_POLICY_NAME = "auditisa-console-policy"
RANDOM_HEX = 12

# The same rule as services/validation.py, which also forbids "--".
_SLUG = r"[a-z][a-z0-9-]{1,30}[a-z0-9]"
FIRM_BUCKET_RE = re.compile(rf"^{FIRM_BUCKET_PREFIX}({_SLUG})-([0-9a-f]{{{RANDOM_HEX}}})$")
RELEASES_BUCKET_RE = re.compile(rf"^{RELEASES_BUCKET_PREFIX}[a-z0-9][a-z0-9-]{{6,40}}[a-z0-9]$")
REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-[0-9]$")
ENDPOINT_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,120}[a-z0-9](:[0-9]{2,5})?$")


def valid_slug(slug):
    return bool(re.fullmatch(_SLUG, slug or "")) and "--" not in slug


def firm_user(slug):
    if not valid_slug(slug):
        raise ValueError("invalid slug")
    return FIRM_USER_PREFIX + slug


def slug_of_label(label):
    """provisioning.label_of(slug) is also the firm's user name: auditisa-firm-<slug>."""
    slug = (label or "")[len(FIRM_USER_PREFIX):] if (label or "").startswith(FIRM_USER_PREFIX) else ""
    if not valid_slug(slug):
        raise ValueError("invalid label")
    return slug


def new_firm_bucket(slug, random_hex=None):
    """auditisa-fw-<slug>-<12 hex>: at most 12 + 32 + 1 + 12 = 57 characters (S3 allows 63)."""
    if not valid_slug(slug):
        raise ValueError("invalid slug")
    random_hex = random_hex or secrets.token_hex(RANDOM_HEX // 2)
    name = f"{FIRM_BUCKET_PREFIX}{slug}-{random_hex}"
    if not FIRM_BUCKET_RE.match(name):
        raise ValueError("invalid bucket name")
    return name


def slug_of_bucket(name):
    """The firm a bucket belongs to, or None. Exact: firm `ab` never matches `ab-cd`'s bucket."""
    match = FIRM_BUCKET_RE.match(name or "")
    if not match or "--" in match.group(1):
        return None
    return match.group(1)


def default_endpoint(region):
    return f"s3.{region}.wasabisys.com"


# ---------------------------------------------------------------------------- the two policies

CONSOLE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            # Bucket names only, to find a firm's bucket again after an interruption. This action
            # cannot be limited to some buckets: it shows the names of all, and nothing inside.
            "Sid": "ListBucketNames",
            "Effect": "Allow",
            "Action": "s3:ListAllMyBuckets",
            "Resource": "*",
        },
        {
            "Sid": "FirmBuckets",
            "Effect": "Allow",
            "Action": [
                "s3:CreateBucket",
                "s3:DeleteBucket",
                "s3:ListBucket",
                "s3:GetBucketLocation",
                "s3:PutBucketPolicy",
            ],
            "Resource": "arn:aws:s3:::auditisa-fw-*",
        },
        {
            # To empty a firm's bucket before deleting it. No read: the console never opens a backup.
            "Sid": "EmptyFirmBucketsBeforeDeletion",
            "Effect": "Allow",
            "Action": "s3:DeleteObject",
            "Resource": "arn:aws:s3:::auditisa-fw-*/*",
        },
        {
            "Sid": "ReleasesBucket",
            "Effect": "Allow",
            "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
            "Resource": "arn:aws:s3:::auditisa-releases-*",
        },
        {
            # Read, to sign download addresses for the firms; write, to upload a release.
            "Sid": "ReleasesFiles",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject"],
            "Resource": "arn:aws:s3:::auditisa-releases-*/*",
        },
        {
            # Users named auditisa-firm-* only (made under the path /auditisa/; the second line covers
            # an ARN written without its path). No action that writes or attaches a policy on a user:
            # the console cannot give any user, itself included, more rights.
            "Sid": "FirmUsersAndTheirKeys",
            "Effect": "Allow",
            "Action": [
                "iam:CreateUser",
                "iam:GetUser",
                "iam:DeleteUser",
                "iam:CreateAccessKey",
                "iam:DeleteAccessKey",
                "iam:ListAccessKeys",
            ],
            "Resource": [
                "arn:aws:iam::*:user/auditisa/auditisa-firm-*",
                "arn:aws:iam::*:user/auditisa-firm-*",
            ],
        },
    ],
}

# What a firm's key may do in its own bucket: what restic needs, nothing more.
FIRM_BUCKET_ACTIONS = ["s3:ListBucket", "s3:GetBucketLocation"]
FIRM_OBJECT_ACTIONS = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]


def firm_bucket_policy(bucket, user_arn):
    slug = slug_of_bucket(bucket)
    if not slug:
        raise ValueError("not a firm's bucket")
    # The user must be this bucket's firm: a mistake can never open one firm's bucket to another.
    if not re.fullmatch(rf"arn:aws:iam::[0-9]{{6,20}}:user/(auditisa/)?{re.escape(firm_user(slug))}", user_arn or ""):
        raise ValueError("not this firm's user")
    principal = {"AWS": user_arn}
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "FirmListsItsBucket",
                "Effect": "Allow",
                "Principal": principal,
                "Action": list(FIRM_BUCKET_ACTIONS),
                "Resource": f"arn:aws:s3:::{bucket}",
            },
            {
                "Sid": "FirmReadsAndWritesItsBackups",
                "Effect": "Allow",
                "Principal": principal,
                "Action": list(FIRM_OBJECT_ACTIONS),
                "Resource": f"arn:aws:s3:::{bucket}/*",
            },
        ],
    }


# ---------------------------------------------------------------------------- the evaluator

ALLOW, DENY, IMPLICIT_DENY = "allow", "deny", "implicit_deny"


def _as_list(value):
    return value if isinstance(value, list) else [value]


def wildcard_match(pattern, value, ignore_case=False):
    """IAM matching: `*` any run of characters (`/` included), `?` exactly one."""
    regex = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(regex, value, re.IGNORECASE if ignore_case else 0) is not None


def _principal_matches(statement, principal):
    if "Principal" not in statement:
        return True  # an identity policy: it speaks for the user it is attached to
    wanted = statement["Principal"]
    if wanted == "*":
        return True
    return any(wildcard_match(p, principal) if p == "*" else p == principal for p in _as_list(wanted.get("AWS", [])))


def evaluate(policies, action, resource, principal=""):
    """ALLOW, DENY (an explicit Deny wins) or IMPLICIT_DENY (nothing allows it)."""
    allowed = False
    for policy in policies:
        for statement in _as_list(policy["Statement"]):
            if not _principal_matches(statement, principal):
                continue
            if not any(wildcard_match(a, action, ignore_case=True) for a in _as_list(statement["Action"])):
                continue
            if not any(wildcard_match(r, resource) for r in _as_list(statement["Resource"])):
                continue
            if statement["Effect"] == "Deny":
                return DENY
            allowed = True
    return ALLOW if allowed else IMPLICIT_DENY
