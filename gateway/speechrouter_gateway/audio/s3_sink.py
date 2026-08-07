"""S3 audio sink: streams session audio to S3 via real multipart upload.

Buffers only up to the 5 MB S3 minimum part size per in-flight part, never
a whole session -- a long or high-concurrency session must not blow up
gateway memory. This is the same lesson ScribeMD's own STT service learned
the hard way (see: "stream WAV upload to S3 instead of loading whole file
into memory").

Stores raw audio bytes exactly as received (whatever encoding/sample_rate
the session declared) plus that encoding/sample_rate/channels as S3 object
metadata, since raw PCM isn't self-describing on its own -- a consumer can
prepend a WAV header from the metadata, or read the PCM directly.

A sink failure must never break transcription: every AWS call here is
wrapped so exceptions are logged, not raised, into the caller.
"""

import asyncio

import httpx

from ..logging import logger
from .s3_signer import sign_s3_request

MIN_PART_SIZE = 5 * 1024 * 1024  # S3's own minimum, except the last part


class _SessionUpload:
    __slots__ = ("buffer", "upload_id", "part_number", "parts", "key")

    def __init__(self, key: str) -> None:
        self.buffer = bytearray()
        self.upload_id: str | None = None
        self.part_number = 1
        self.parts: list[tuple[int, str]] = []
        self.key = key


class S3AudioSink:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key: str,
        secret_key: str,
        prefix: str = "",
        session_token: str = "",
        client: httpx.AsyncClient | None = None,
    ):
        self._bucket = bucket
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._prefix = prefix.strip("/")
        self._session_token = session_token
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._uploads: dict[str, _SessionUpload] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def _sign(
        self, method: str, key: str, query: dict[str, str] | None = None,
        payload: bytes = b"", extra_headers: dict[str, str] | None = None,
    ):
        signed = sign_s3_request(
            method=method, bucket=self._bucket, key=key, region=self._region,
            access_key=self._access_key, secret_key=self._secret_key,
            query=query, payload=payload, session_token=self._session_token,
        )
        headers = dict(signed.headers)
        if extra_headers:
            headers.update(extra_headers)
        return signed.url, headers

    async def _initiate(self, key: str) -> str:
        url, headers = self._sign("POST", key, query={"uploads": ""})
        resp = await self._client.post(url, headers=headers)
        resp.raise_for_status()
        # <InitiateMultipartUploadResult><UploadId>...</UploadId></...>
        text = resp.text
        start = text.index("<UploadId>") + len("<UploadId>")
        end = text.index("</UploadId>")
        return text[start:end]

    async def _upload_part(self, key: str, upload_id: str, part_number: int, data: bytes) -> str:
        url, headers = self._sign(
            "PUT", key,
            query={"partNumber": str(part_number), "uploadId": upload_id},
            payload=bytes(data),
        )
        resp = await self._client.put(url, headers=headers, content=bytes(data))
        resp.raise_for_status()
        etag = resp.headers.get("ETag", "")
        return etag

    async def _complete(self, key: str, upload_id: str, parts: list[tuple[int, str]]) -> None:
        body_parts = "".join(
            f"<Part><PartNumber>{n}</PartNumber><ETag>{etag}</ETag></Part>"
            for n, etag in parts
        )
        body = (
            '<CompleteMultipartUpload xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"{body_parts}</CompleteMultipartUpload>"
        ).encode()
        url, headers = self._sign(
            "POST", key, query={"uploadId": upload_id}, payload=body,
            extra_headers={"Content-Type": "application/xml"},
        )
        resp = await self._client.post(url, headers=headers, content=body)
        resp.raise_for_status()

    async def _abort(self, key: str, upload_id: str) -> None:
        url, headers = self._sign("DELETE", key, query={"uploadId": upload_id})
        resp = await self._client.delete(url, headers=headers)
        resp.raise_for_status()

    def _object_key(self, session_id: str) -> str:
        base = f"{self._prefix}/{session_id}.raw" if self._prefix else f"{session_id}.raw"
        return base

    async def on_chunk(self, session_id: str, chunk: bytes) -> None:
        try:
            async with self._lock(session_id):
                upload = self._uploads.get(session_id)
                if upload is None:
                    upload = _SessionUpload(self._object_key(session_id))
                    self._uploads[session_id] = upload
                upload.buffer.extend(chunk)
                if len(upload.buffer) < MIN_PART_SIZE:
                    return
                if upload.upload_id is None:
                    upload.upload_id = await self._initiate(upload.key)
                part_data = bytes(upload.buffer)
                upload.buffer.clear()
                etag = await self._upload_part(
                    upload.key, upload.upload_id, upload.part_number, part_data
                )
                upload.parts.append((upload.part_number, etag))
                upload.part_number += 1
        except Exception:  # noqa: BLE001 - a sink must never break transcription
            logger.error("audio sink chunk failed", exc_info=True,
                         extra={"session": session_id})

    async def on_session_end(self, session_id: str) -> None:
        upload: _SessionUpload | None = None
        try:
            async with self._lock(session_id):
                upload = self._uploads.pop(session_id, None)
                self._locks.pop(session_id, None)
                if upload is None:
                    return
                if upload.upload_id is None:
                    # under 5MB total: a single-part upload, no multipart needed
                    if upload.buffer:
                        url, headers = self._sign("PUT", upload.key, payload=bytes(upload.buffer))
                        resp = await self._client.put(
                            url, headers=headers, content=bytes(upload.buffer)
                        )
                        resp.raise_for_status()
                    return
                if upload.buffer:
                    etag = await self._upload_part(
                        upload.key, upload.upload_id, upload.part_number, bytes(upload.buffer)
                    )
                    upload.parts.append((upload.part_number, etag))
                await self._complete(upload.key, upload.upload_id, upload.parts)
        except Exception:  # noqa: BLE001 - a sink must never break transcription
            logger.error("audio sink finalize failed", exc_info=True,
                         extra={"session": session_id})
            if upload is not None and upload.upload_id is not None:
                try:
                    await self._abort(upload.key, upload.upload_id)
                except Exception:  # noqa: BLE001
                    logger.error("audio sink abort failed", exc_info=True,
                                 extra={"session": session_id})
