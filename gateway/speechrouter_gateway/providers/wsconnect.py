"""Shared WebSocket dialer for all provider adapters.

asyncio tries resolved addresses sequentially by default: on networks with a
broken IPv6 route, the v6 attempt must fully time out before v4 is tried,
which intermittently blows the opening handshake (seen live: Soniox/Flux
"timed out during opening handshake" while the next attempt succeeds).
happy_eyeballs_delay races v6/v4 in parallel; open_timeout gets headroom.
"""

import websockets


async def ws_connect(url: str, **kwargs) -> websockets.ClientConnection:
    kwargs.setdefault("open_timeout", 15)
    kwargs.setdefault("happy_eyeballs_delay", 0.25)
    return await websockets.connect(url, **kwargs)
