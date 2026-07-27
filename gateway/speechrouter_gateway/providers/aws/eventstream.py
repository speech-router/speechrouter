# Derived from Amazon sample code. Copyright Amazon.com, Inc. or affiliates.
# SPDX-License-Identifier: MIT-0
"""AWS event-stream binary framing (prelude + headers + payload + CRC32s).

Wire layout: 4B BE total length | 4B BE headers length | 4B prelude CRC32 |
headers | payload | 4B message CRC32. Header: 1B name-len, name, 1B value
type (7 = string), 2B BE value-len, value.
"""

import binascii
import struct

_STRING_TYPE = 7


class EventStreamError(Exception):
    pass


def encode_headers(headers: dict[str, str]) -> bytes:
    out = bytearray()
    for name, value in headers.items():
        encoded_name = name.encode()
        encoded_value = value.encode()
        out.append(len(encoded_name))
        out.extend(encoded_name)
        out.append(_STRING_TYPE)
        out.extend(struct.pack(">H", len(encoded_value)))
        out.extend(encoded_value)
    return bytes(out)


def build_message(headers: dict[str, str], payload: bytes) -> bytes:
    header_bytes = encode_headers(headers)
    total = len(header_bytes) + len(payload) + 16  # 8B prelude + 2x 4B CRC
    prelude = struct.pack(">II", total, len(header_bytes))
    prelude_crc = struct.pack(">I", binascii.crc32(prelude) & 0xFFFFFFFF)
    body = prelude + prelude_crc + header_bytes + payload
    message_crc = struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
    return body + message_crc


def build_audio_event(payload: bytes) -> bytes:
    return build_message(
        {
            ":content-type": "application/octet-stream",
            ":event-type": "AudioEvent",
            ":message-type": "event",
        },
        payload,
    )


def decode_message(message: bytes) -> tuple[dict[str, str], bytes]:
    if len(message) < 16:
        raise EventStreamError(f"frame too short: {len(message)} bytes")
    total_length, headers_length = struct.unpack(">II", message[:8])
    prelude_crc = struct.unpack(">I", message[8:12])[0]
    if prelude_crc != binascii.crc32(message[:8]) & 0xFFFFFFFF:
        raise EventStreamError("prelude CRC mismatch")
    message_crc = struct.unpack(">I", message[-4:])[0]
    if message_crc != binascii.crc32(message[:-4]) & 0xFFFFFFFF:
        raise EventStreamError("message CRC mismatch")

    headers: dict[str, str] = {}
    buf = message[12 : 12 + headers_length]
    while buf:
        name_len = buf[0]
        name = buf[1 : 1 + name_len].decode()
        value_len = struct.unpack(">H", buf[2 + name_len : 4 + name_len])[0]
        headers[name] = buf[4 + name_len : 4 + name_len + value_len].decode()
        buf = buf[4 + name_len + value_len :]
    payload = message[12 + headers_length : -4]
    return headers, payload
