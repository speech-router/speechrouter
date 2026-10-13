# Derived from Amazon sample code. Copyright Amazon.com, Inc. or affiliates.
# SPDX-License-Identifier: MIT-0
"""SigV4 presigned URL for the Transcribe streaming WebSocket.

Canonical querystring params MUST be alphabetically ordered — arbitrary
passthrough params would break the signature, which is why the adapter does
not forward provider_params to AWS.
"""

import datetime
import hashlib
import hmac
import urllib.parse


def _hmac(key: bytes, data: str) -> bytes:
    return hmac.new(key, data.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k = _hmac(f"AWS4{secret}".encode(), datestamp)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def presigned_url(
    *,
    access_key: str,
    secret_key: str,
    region: str,
    sample_rate: int,
    language_code: str | None,
    media_encoding: str = "pcm",
    show_speaker_label: bool = False,
    enable_partial_results_stabilization: bool = True,
    partial_results_stability: str = "medium",
    session_token: str = "",
    now: datetime.datetime | None = None,
) -> str:
    service = "transcribe"
    host = f"transcribestreaming.{region}.amazonaws.com:8443"
    uri = "/stream-transcription-websocket"
    now = now or datetime.datetime.now(datetime.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"

    params: list[tuple[str, str]] = [
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{access_key}/{scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", "300"),
    ]
    if session_token:
        params.append(("X-Amz-Security-Token", session_token))
    params.append(("X-Amz-SignedHeaders", "host"))
    if enable_partial_results_stabilization:
        params.append(("enable-partial-results-stabilization", "true"))
    if language_code:
        params.append(("language-code", language_code))
    else:
        params.append(("identify-language", "true"))
        params.append(("language-options", "en-US,es-US"))
    params.append(("media-encoding", media_encoding))
    if enable_partial_results_stabilization and partial_results_stability:
        params.append(("partial-results-stability", partial_results_stability))
    params.append(("sample-rate", str(sample_rate)))
    if show_speaker_label:
        params.append(("show-speaker-label", "true"))

    # SigV4 requires the canonical querystring sorted by encoded name.
    encoded = sorted(
        (urllib.parse.quote(k, safe=""), urllib.parse.quote(v, safe="")) for k, v in params
    )
    querystring = "&".join(f"{k}={v}" for k, v in encoded)

    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_request = (
        f"GET\n{uri}\n{querystring}\nhost:{host}\n\nhost\n{payload_hash}"
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
    return f"wss://{host}{uri}?{querystring}&X-Amz-Signature={signature}"


def sign_headers(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    session_token: str = "",
    content_sha256_header: bool = True,
    now: datetime.datetime | None = None,
) -> dict[str, str]:
    """SigV4 header signing for plain HTTPS APIs (Polly SynthesizeSpeech).

    Returns the headers to send: the caller's headers plus host, x-amz-date,
    x-amz-content-sha256, optional x-amz-security-token and Authorization.
    Every returned header is signed.
    """
    parsed = urllib.parse.urlsplit(url)
    now = now or datetime.datetime.now(datetime.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    payload_hash = hashlib.sha256(body).hexdigest()

    signed = {k.lower(): " ".join(v.strip().split()) for k, v in headers.items()}
    signed["host"] = parsed.netloc
    signed["x-amz-date"] = amz_date
    if content_sha256_header:
        signed["x-amz-content-sha256"] = payload_hash
    if session_token:
        signed["x-amz-security-token"] = session_token
    names = sorted(signed)
    canonical_headers = "".join(f"{n}:{signed[n]}\n" for n in names)
    signed_headers = ";".join(names)

    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}"
        for k, v in sorted(query)
    )
    canonical_uri = urllib.parse.quote(parsed.path or "/", safe="/-_.~")
    canonical_request = "\n".join([
        method.upper(), canonical_uri, canonical_query, canonical_headers, signed_headers,
        payload_hash,
    ])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])
    signature = hmac.new(_signing_key(secret_key, datestamp, region, service),
                         string_to_sign.encode(), hashlib.sha256).hexdigest()
    out = {k: v for k, v in signed.items() if k != "host"}
    out["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                            f"SignedHeaders={signed_headers}, Signature={signature}")
    return out
