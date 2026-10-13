# PlayHT (PlayAI)

## Status
- **Treat as SHUT DOWN. Do not integrate.**
- Verified by me on 2026-10-13 from the agent server:
  - `play.ht`, `www.play.ht`, `api.play.ht` and `play.ai` do not resolve in DNS (`getaddrinfo ENOTFOUND` and `curl: Could not resolve host`).
  - `docs.play.ht` still serves a STALE static docs site. It shows no shutdown notice, its last-updated stamp is 2025-09-09, and it lists the endpoint `POST https://api.play.ht/api/v2/tts/stream` (https://docs.play.ht/reference/api-getting-started). That endpoint's host is dead.
- Acquisition, confirmed by TechCrunch (https://techcrunch.com/2025/07/13/meta-acquires-voice-startup-play-ai/) and Bloomberg (https://www.bloomberg.com/news/articles/2025-07-11/meta-acquires-voice-ai-startup-playai-continuing-to-add-talent): Meta acquired the PlayAI (formerly PlayHT) team in July 2025. Neither source mentions a service shutdown.
- Shutdown dates are UNVERIFIED from any PlayHT-owned source. No official notice was reachable.
  - Secondary claims: the API went offline about 2025-07-26 and the full platform sunset on 2025-12-31. These come from an Inworld migration guide (a competitor, https://inworld.ai/resources/migrate-from-playht, dated 2026-07-07) quoting a Cartesia remark, and from third-party blogs.
  - Official-ish evidence of the outage is the DNS failure above.
- Stopping here as instructed. The sections below are intentionally minimal.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- Not applicable. The last documented endpoint was `POST https://api.play.ht/api/v2/tts/stream`, with headers `X-USER-ID` and `AUTHORIZATION` (the API key). The host no longer resolves. Body schema: UNVERIFIED and not pursued.

## Output formats
- Not applicable (shut down). UNVERIFIED.

## Models
- Not applicable. The stale docs listed PlayDialog, Play 3.0 Mini and Play 2.0 (`PlayHT2.0-turbo`) (https://docs.play.ht/reference/models.md). Do not use them.

## Voices
- Not applicable.

## WebSocket / input streaming
- Not applicable.

## Usage reporting
- Not applicable.

## Pricing (list price, pay-as-you-go/API)
- Not applicable (service unavailable). Checked 2026-10-13.

## Errors
- Not applicable. Calls fail at DNS resolution.
