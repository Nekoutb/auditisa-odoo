"""AWS Signature Version 4, which Wasabi's S3 and IAM endpoints speak. Pure: stdlib only.

Two uses: signing a request in its headers (the console's calls to Wasabi), and a presigned address
(a firm or the practice computer downloads one release file without holding any key). The tests
check both against AWS's published examples.

The secret key goes in and only signatures come out: it is never placed in a header, an address,
an error or a repr.
"""

import hashlib
import hmac
from urllib.parse import quote, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
# SigV4 refuses a presigned address valid for more than seven days.
MAX_PRESIGN_SECONDS = 7 * 24 * 3600


def _hmac(key, text):
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


def _uri_encode(text, safe="-_.~"):
    return quote(text, safe=safe)


def canonical_query(query):
    """`query`: a list of (name, value) pairs, unencoded. Sorted and encoded as SigV4 wants."""
    pairs = sorted((_uri_encode(str(name)), _uri_encode(str(value))) for name, value in query)
    return "&".join(f"{name}={value}" for name, value in pairs)


def signing_key(secret_key, date, region, service):
    key = _hmac(("AWS4" + secret_key).encode("utf-8"), date)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


def _signature(secret_key, amz_date, region, service, canonical_request):
    date = amz_date[:8]
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join((
        ALGORITHM, amz_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ))
    return scope, hmac.new(signing_key(secret_key, date, region, service), to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def _path(url, service):
    path = urlsplit(url).path or "/"
    # S3 paths are encoded once; every other service encodes them twice.
    encoded = _uri_encode(path, safe="/-_.~")
    return encoded if service == "s3" else _uri_encode(encoded, safe="/-_.~")


def sign_headers(method, url, query, headers, body, access_key, secret_key, region, service, amz_date):
    """The headers to send: `headers` plus host, x-amz-date, x-amz-content-sha256 and Authorization.

    `query` is the list of query pairs, unencoded, that the caller puts on the address itself (with
    `canonical_query`, so that what is signed is what is sent). `amz_date`: YYYYMMDDTHHMMSSZ.
    """
    body = body or b""
    payload_hash = hashlib.sha256(body).hexdigest()
    signed = {name.lower(): " ".join(str(value).split()) for name, value in headers.items()}
    signed["host"] = urlsplit(url).netloc
    signed["x-amz-date"] = amz_date
    if service == "s3":
        signed["x-amz-content-sha256"] = payload_hash
    names = sorted(signed)
    canonical_request = "\n".join((
        method,
        _path(url, service),
        canonical_query(query),
        "".join(f"{name}:{signed[name]}\n" for name in names),
        ";".join(names),
        payload_hash,
    ))
    scope, signature = _signature(secret_key, amz_date, region, service, canonical_request)
    result = dict(headers)
    result["x-amz-date"] = amz_date
    if service == "s3":
        result["x-amz-content-sha256"] = payload_hash
    result["Authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return result


def presign_url(url, access_key, secret_key, region, amz_date, expires, service="s3"):
    """A GET address valid `expires` seconds from `amz_date`, signed by the key's owner."""
    expires = int(expires)
    if not 1 <= expires <= MAX_PRESIGN_SECONDS:
        raise ValueError("a presigned address lasts from one second to seven days")
    parts = urlsplit(url)
    if parts.query:
        raise ValueError("the address must have no query of its own")
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    query = [
        ("X-Amz-Algorithm", ALGORITHM),
        ("X-Amz-Credential", f"{access_key}/{scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(expires)),
        ("X-Amz-SignedHeaders", "host"),
    ]
    canonical_request = "\n".join((
        "GET",
        _path(url, service),
        canonical_query(query),
        f"host:{parts.netloc}\n",
        "host",
        UNSIGNED_PAYLOAD,
    ))
    _scope, signature = _signature(secret_key, amz_date, region, service, canonical_request)
    path = _path(url, service)
    return f"{parts.scheme}://{parts.netloc}{path}?{canonical_query(query)}&X-Amz-Signature={signature}"
