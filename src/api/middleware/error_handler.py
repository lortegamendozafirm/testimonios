from fastapi import Request
from fastapi.responses import JSONResponse
import logging
logger = logging.getLogger(__name__)

async def unhandled_exception_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"detail": str(e)})