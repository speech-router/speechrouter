"""GET /v1/models — public model catalog."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request) -> dict:
    return {"object": "list", "data": request.app.state.catalog.all()}
