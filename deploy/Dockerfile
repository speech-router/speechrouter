# SpeechRouter gateway — the ONE image for self-host and cloud.
# Behavior is selected by env (SPEECHROUTER_KEYSTORE / SPEECHROUTER_USAGE_EMITTER).

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY gateway/pyproject.toml gateway/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY gateway/ ./
RUN uv sync --frozen --no-dev

FROM python:3.14-slim-trixie
RUN useradd --create-home --uid 1000 speechrouter
WORKDIR /app
COPY --from=build --chown=speechrouter:speechrouter /app /app
USER speechrouter
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/up')"
CMD ["uvicorn", "speechrouter_gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
