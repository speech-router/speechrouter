"""Hand-rolled SigV4 for the S3 REST API (multipart upload) -- same
no-heavy-SDK discipline as providers/aws/signer.py, kept separate and
self-contained rather than shared, so this module can't regress the AWS
Transcribe adapter's signing and vice versa.

Covers exactly the three calls a streaming multipart upload needs:
initiate, upload a part, complete. Header-based (Authorization header),
not query-string presigning -- these are real PUT/POST bodies, not a
one-shot WS handshake URL.
"""

import datetime
import hashlib
import hmac
import urllib.parse
from dataclasses import dataclass


def _hmac(key: bytes, data: str) -> bytes:
    return hmac.new(key, data.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k = _hmac(f"AWS4{secret}".encode(), datestamp)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


@dataclass(frozen=True)
class SignedRequest:
    url: str
    headers: dict[str, str]


def sign_s3_request(
    *,
    method: str,
    bucket: str,
    key: str,
    region: str,
    access_key: str,
    secret_key: str,
    query: dict[str, str] | None = None,
    payload: bytes = b"",
    session_token: str = "",
    now: datetime.datetime | None = None,
) -> SignedRequest:
    service = "s3"
    host = f"{bucket}.s3.{region}.amazonaws.com"
    uri = "/" + urllib.parse.quote(key, safe="/")
    now = now or datetime.datetime.now(datetime.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"

    payload_hash = hashlib.sha256(payload).hexdigest()
    query = query or {}
    canonical_qs = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(query.items())
    )

    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if session_token:
        headers["x-amz-security-token"] = session_token
    signed_header_names = sorted(headers.keys())
    canonical_headers = "".join(f"{h}:{headers[h]}\n" for h in signed_header_names)
    signed_headers = ";".join(signed_header_names)

    canonical_request = (
        f"{method}\n{uri}\n{canonical_qs}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{amz_date}\n{scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, service),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    auth = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    out_headers = {k: v for k, v in headers.items() if k != "host"}
    out_headers["Authorization"] = auth

    url = f"https://{host}{uri}"
    if canonical_qs:
        url += f"?{canonical_qs}"
    return SignedRequest(url=url, headers=out_headers)
