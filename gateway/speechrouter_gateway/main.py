"""SpeechRouter gateway entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.listen_ws import router as listen_router
from .api.models import router as models_router
from .auth import build_keystore
from .config import KeyStoreKind, settings
from .logging import logger, setup_logging
from .metering import build_emitter
from .router.catalog import Catalog


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = settings()
    app.state.settings = cfg
    app.state.keystore = build_keystore(cfg)
    app.state.emitter = build_emitter(cfg)
    app.state.catalog = Catalog.load()
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
app.include_router(models_router)
app.include_router(listen_router)


@app.get("/up")
async def up() -> dict:
    return {"status": "ok"}
