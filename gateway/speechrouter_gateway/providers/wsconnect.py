"""Shared WebSocket dialer for all provider adapters.

Two concerns:
- open_timeout headroom (15s): live testing showed intermittent
  "timed out during opening handshake" on cold dials.
- Happy Eyeballs (RFC 8305): stdlib asyncio dials resolved addresses
  sequentially, so a broken IPv6 route stalls the whole handshake.
  asyncio.create_connection supports happy_eyeballs_delay — but uvloop
  (uvicorn's default loop) does NOT accept that kwarg, so it is applied
  only when the running loop supports it.
"""

import websockets


async def ws_connect(url: str, **kwargs) -> websockets.ClientConnection:
    kwargs.setdefault("open_timeout", 15)
    try:
        return await websockets.connect(url, happy_eyeballs_delay=0.25, **kwargs)
    except TypeError:
        # uvloop's create_connection() rejects happy_eyeballs_delay.
        return await websockets.connect(url, **kwargs)
