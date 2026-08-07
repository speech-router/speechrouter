"""AudioSink: NoOp default, S3 signer structure, S3AudioSink flow (mocked
HTTP -- no real AWS needed for CI). The signer + full multipart flow were
also live-verified against real S3 during development (5.24MB across two
parts, plus the single-PUT small-file path, byte-exact SHA256 match)."""


import httpx

from speechrouter_gateway.audio.s3_signer import sign_s3_request
from speechrouter_gateway.audio.s3_sink import MIN_PART_SIZE, S3AudioSink
from speechrouter_gateway.audio.sink import NoOpAudioSink


async def test_noop_sink_does_nothing():
    sink = NoOpAudioSink()
    await sink.on_chunk("sess_1", b"audio")
    await sink.on_session_end("sess_1")  # neither call should raise


def test_sign_s3_request_structure():
    signed = sign_s3_request(
        method="PUT", bucket="my-bucket", key="a/b.raw", region="us-east-1",
        access_key="AKIA_TEST", secret_key="secret", payload=b"hello",
    )
    assert signed.url.startswith("https://my-bucket.s3.us-east-1.amazonaws.com/a/b.raw")
    assert signed.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIA_TEST/")
    assert "x-amz-content-sha256" in signed.headers
    assert "x-amz-date" in signed.headers


def test_sign_s3_request_is_deterministic_for_same_instant():
    import datetime

    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    a = sign_s3_request(
        method="GET", bucket="b", key="k", region="us-east-1",
        access_key="ak", secret_key="sk", now=now,
    )
    b = sign_s3_request(
        method="GET", bucket="b", key="k", region="us-east-1",
        access_key="ak", secret_key="sk", now=now,
    )
    assert a.headers["Authorization"] == b.headers["Authorization"]


def _mock_s3_transport(calls: list[tuple[str, str]]):
    """Records (method, path) and returns plausible S3 responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and "uploads" in request.url.params:
            return httpx.Response(
                200,
                content=(
                    "<InitiateMultipartUploadResult>"
                    "<UploadId>test-upload-id</UploadId>"
                    "</InitiateMultipartUploadResult>"
                ),
            )
        if request.method == "PUT" and "partNumber" in request.url.params:
            n = request.url.params["partNumber"]
            return httpx.Response(200, headers={"ETag": f'"etag-{n}"'})
        if request.method == "POST" and "uploadId" in request.url.params:
            return httpx.Response(200, content="<CompleteMultipartUploadResult/>")
        if request.method == "PUT":
            return httpx.Response(200, headers={"ETag": '"whole-object-etag"'})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_small_session_does_a_single_put_not_multipart():
    calls: list[tuple[str, str]] = []
    client = httpx.AsyncClient(transport=_mock_s3_transport(calls))
    sink = S3AudioSink(
        bucket="b", region="us-east-1", access_key="ak", secret_key="sk", client=client,
    )
    await sink.on_chunk("sess_small", b"tiny audio chunk")
    await sink.on_session_end("sess_small")
    assert calls == [("PUT", "/sess_small.raw")]


async def test_large_session_does_full_multipart_flow():
    calls: list[tuple[str, str]] = []
    client = httpx.AsyncClient(transport=_mock_s3_transport(calls))
    sink = S3AudioSink(
        bucket="b", region="us-east-1", access_key="ak", secret_key="sk",
        prefix="rec", client=client,
    )
    # one chunk over the part-size boundary triggers initiate + first part
    await sink.on_chunk("sess_big", b"x" * (MIN_PART_SIZE + 10))
    # a second, smaller chunk becomes the final part on session_end
    await sink.on_chunk("sess_big", b"y" * 100)
    await sink.on_session_end("sess_big")

    methods_and_paths = [c for c in calls]
    assert ("POST", "/rec/sess_big.raw") in methods_and_paths  # initiate
    put_calls = [c for c in calls if c[0] == "PUT"]
    assert len(put_calls) == 2  # two parts uploaded
    complete_calls = [c for c in calls if c[0] == "POST"]
    assert len(complete_calls) == 2  # initiate + complete


async def test_sink_errors_never_raise_into_the_caller():
    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(failing_handler))
    sink = S3AudioSink(
        bucket="b", region="us-east-1", access_key="ak", secret_key="sk", client=client,
    )
    # a real S3 500 would raise inside the sink -- must be swallowed, not
    # propagated, since a sink failure must never break transcription
    await sink.on_chunk("sess_err", b"x" * (MIN_PART_SIZE + 10))
    await sink.on_session_end("sess_err")  # neither call raises
