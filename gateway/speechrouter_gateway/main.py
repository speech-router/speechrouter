"""SpeechRouter gateway entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.listen_ws import router as listen_router
from .api.models import router as models_router
from .api.tokens import router as tokens_router
from .api.transcriptions import router as transcriptions_router
from .auth import build_keystore
from .auth.tokens import LocalTokenStore, RedisTokenStore
from .config import KeyStoreKind, settings
from .logging import logger, setup_logging
from .metering import build_emitter
from .router.catalog import Catalog
from .router.limits import ConcurrencyGuard


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = settings()
    app.state.settings = cfg
    app.state.keystore = build_keystore(cfg)
    app.state.token_store = (
        RedisTokenStore(app.state.keystore.redis)  # type: ignore[attr-defined]
        if cfg.keystore == KeyStoreKind.cloud
        else LocalTokenStore()
    )
    app.state.emitter = build_emitter(cfg)
    app.state.catalog = Catalog.load()
    app.state.concurrency = ConcurrencyGuard(limit=cfg.max_concurrent_streams)
    if cfg.keystore == KeyStoreKind.none:
        logger.warning("AUTH IS DISABLED (SPEECHROUTER_KEYSTORE=none) — dev mode only")
    logger.info(
        "gateway starting",
        extra={
            "keystore": cfg.keystore.value,
            "usage_emitter": cfg.usage_emitter.value,
            "models": len(app.state.catalog.all()),
        },
    )
    yield
    logger.info("gateway stopped")


app = FastAPI(title="SpeechRouter", lifespan=lifespan)
# Browsers (playground, dashboards) call the REST surface directly; the API
# is key-authenticated, so open CORS is the correct posture for a gateway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(models_router)
app.include_router(listen_router)
app.include_router(transcriptions_router)
app.include_router(tokens_router)


@app.exception_handler(RequestValidationError)
async def validation_envelope(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Framework validation errors wear the same envelope as every other
    error — nobody should ever see raw {"detail": [...]}."""
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(part) for part in first.get("loc", []) if part not in ("body", "query"))
    msg = first.get("msg", "invalid request")
    message = f"{loc}: {msg}" if loc else msg
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "invalid_request", "message": message,
                           "type": "invalid_request_error"}},
    )


@app.get("/up")
async def up() -> dict:
    return {"status": "ok"}
