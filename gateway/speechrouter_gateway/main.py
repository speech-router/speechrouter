"""SpeechRouter gateway entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.listen_ws import router as listen_router
from .api.models import router as models_router
from .api.transcriptions import router as transcriptions_router
from .auth import build_keystore
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


@app.get("/up")
async def up() -> dict:
    return {"status": "ok"}
