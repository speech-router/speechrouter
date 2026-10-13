#!/usr/bin/env bash
# Local TTS + live smoke test: mock upstream -> local gateway (TLS) -> official SDKs.
#
# No provider keys, no cloud: the gateway's "house" keys are fake values the
# mock upstream checks for. Usage is captured from the gateway's log emitter
# (the same asdict(UsageEvent) payload the Redis emitter XADDs), so the run
# touches no shared state — the server's Redis is used by other sessions.
#
#   scripts/smoke/run_smoke.sh <out_dir>
#
# Needs: gateway/.venv (uv sync), openssl, a local Redis, and a client venv with
#   openai[realtime] google-genai websockets httpx  (SMOKE_VENV, default /tmp/sr-smoke/venv)
set -euo pipefail
OUT="${1:?usage: run_smoke.sh <out_dir>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${SMOKE_VENV:-/tmp/sr-smoke/venv}"
GW_PORT="${SMOKE_GW_PORT:-18787}"
MOCK_PORT="${SMOKE_MOCK_PORT:-18788}"
PY="$ROOT/gateway/.venv/bin/python"  # direct, so the trap kills the real server pids
for port in "$GW_PORT" "$MOCK_PORT"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "port $port is busy; set SMOKE_GW_PORT/SMOKE_MOCK_PORT" >&2; exit 2
  fi
done
mkdir -p "$OUT"
WORK="$(mktemp -d)"
PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; wait 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

# google-genai always dials wss:// for Live, so the local gateway speaks TLS
# with a throwaway self-signed cert that only the smoke clients trust.
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=127.0.0.1" \
  -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" \
  -keyout "$WORK/key.pem" -out "$WORK/cert.pem" 2>/dev/null

"$PY" "$ROOT/scripts/smoke/mock_upstream.py" --port "$MOCK_PORT" \
  > "$OUT/mock-upstream.log" 2>&1 &
PIDS+=($!)

(
  cd "$ROOT/gateway"
  SPEECHROUTER_KEYSTORE=local \
  SPEECHROUTER_KEYS=sk_local_smoke \
  SPEECHROUTER_USAGE_EMITTER=log \
  SPEECHROUTER_OPENAI_API_KEY=mock-house-openai \
  SPEECHROUTER_GEMINI_API_KEY=mock-house-gemini \
  SPEECHROUTER_OPENAI_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" \
  SPEECHROUTER_GEMINI_BASE_URL="http://127.0.0.1:$MOCK_PORT" \
  SPEECHROUTER_ELEVENLABS_API_KEY=mock-house-elevenlabs \
  SPEECHROUTER_CARTESIA_API_KEY=mock-house-cartesia \
  SPEECHROUTER_DEEPGRAM_API_KEY=mock-house-deepgram \
  SPEECHROUTER_AZURE_SPEECH_KEY=mock-house-azure \
  SPEECHROUTER_GOOGLE_TTS_API_KEY=mock-house-google \
  SPEECHROUTER_RIME_API_KEY=mock-house-rime \
  SPEECHROUTER_INWORLD_API_KEY=mock-house-inworld \
  SPEECHROUTER_FISHAUDIO_API_KEY=mock-house-fishaudio \
  SPEECHROUTER_MINIMAX_API_KEY=mock-house-minimax \
  SPEECHROUTER_GROQ_API_KEY=mock-house-groq \
  SPEECHROUTER_MURF_API_KEY=mock-house-murf \
  SPEECHROUTER_SPEECHMATICS_API_KEY=mock-house-speechmatics \
  SPEECHROUTER_AZURE_SPEECH_REGION=eastus \
  SPEECHROUTER_TTS_BASE_URLS="{\"elevenlabs\":\"http://127.0.0.1:$MOCK_PORT/vendor/elevenlabs\",\"cartesia\":\"http://127.0.0.1:$MOCK_PORT/vendor/cartesia\",\"deepgram\":\"http://127.0.0.1:$MOCK_PORT/vendor/deepgram\",\"azure\":\"http://127.0.0.1:$MOCK_PORT/vendor/azure\",\"google\":\"http://127.0.0.1:$MOCK_PORT/vendor/google\",\"rime\":\"http://127.0.0.1:$MOCK_PORT/vendor/rime\",\"inworld\":\"http://127.0.0.1:$MOCK_PORT/vendor/inworld\",\"fishaudio\":\"http://127.0.0.1:$MOCK_PORT/vendor/fishaudio\",\"minimax\":\"http://127.0.0.1:$MOCK_PORT/vendor/minimax\",\"groq\":\"http://127.0.0.1:$MOCK_PORT/vendor/groq\",\"murf\":\"http://127.0.0.1:$MOCK_PORT/vendor/murf\",\"speechmatics\":\"http://127.0.0.1:$MOCK_PORT/vendor/speechmatics\"}" \
  exec "$PY" -m uvicorn speechrouter_gateway.main:app --host 127.0.0.1 --port "$GW_PORT" \
    --ssl-keyfile "$WORK/key.pem" --ssl-certfile "$WORK/cert.pem" --log-level warning
) > "$OUT/gateway.log" 2>&1 &
PIDS+=($!)

for _ in $(seq 1 60); do
  curl -sk "https://127.0.0.1:$GW_PORT/up" >/dev/null 2>&1 && \
    curl -s "http://127.0.0.1:$MOCK_PORT/_seen" >/dev/null 2>&1 && break
  sleep 0.5
done

curl -sk "https://127.0.0.1:$GW_PORT/v1/models" | "$VENV/bin/python" -c '
import json, sys
models = json.load(sys.stdin)["data"]
for m in models:
    if m["kind"] in ("tts", "live"):
        print("%-5s %-52s %s" % (m["kind"], m["slug"], sorted(m["pricing"])))
' > "$OUT/catalog-tts-live.txt"

set +e
SSL_CERT_FILE="$WORK/cert.pem" SMOKE_GATEWAY_KEY=sk_local_smoke \
  "$VENV/bin/python" "$ROOT/scripts/smoke/smoke_clients.py" \
  --base "https://127.0.0.1:$GW_PORT" --mock "http://127.0.0.1:$MOCK_PORT" \
  --gateway-log "$OUT/gateway.log" --out "$OUT"
status=$?
exit $status
