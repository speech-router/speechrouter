"""GET /v1/models — public model catalog."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request, include_disabled: bool = False) -> dict:
    """`?include_disabled=true`: also flag-gated kinds (TTS/live before launch),
    marked "enabled": false — for cloud's price sync, never for routing."""
    catalog = request.app.state.catalog
    return {"object": "list", "data": catalog.public(include_disabled=include_disabled)}
