"""SpeechRouter gateway entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import KeyStoreKind, settings
from .logging import logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = settings()
    if cfg.keystore == KeyStoreKind.none:
        logger.warning("AUTH IS DISABLED (SPEECHROUTER_KEYSTORE=none) — dev mode only")
    logger.info(
        "gateway starting",
        extra={"keystore": cfg.keystore.value, "usage_emitter": cfg.usage_emitter.value},
    )
    yield
    logger.info("gateway stopped")


app = FastAPI(title="SpeechRouter", lifespan=lifespan)


@app.get("/up")
async def up() -> dict:
    return {"status": "ok"}
