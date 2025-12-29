import logging
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> PlainTextResponse:
    logger.info("GET /healthz")
    return PlainTextResponse(content="OK", status_code=200)

