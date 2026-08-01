"""EconRadar FastAPI application entrypoint.

Run locally:  uvicorn main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from db import dispose_engine
from logging_config import configure_logging, get_logger
from routers import ai_router, data_router, health_router
from scheduler import shutdown_scheduler, start_scheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "EconRadar backend starting (env=%s, version=%s)",
        settings.environment,
        settings.app_version,
    )
    start_scheduler()  # non-fatal if disabled or no DATABASE_URL
    try:
        yield
    finally:
        logger.info("EconRadar backend shutting down")
        shutdown_scheduler()
        await dispose_engine()


app = FastAPI(
    title="EconRadar API",
    version=settings.app_version,
    description="AI-native economic intelligence — live data, forecasting, narration, RAG.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """Refuse an oversized body before anything reads it (decision #43).

    The Pydantic schemas bound each *field*, which is the right place for the
    limits a caller should be told about. This is the floor beneath them: a
    100 MB body is rejected on its declared length, before FastAPI buffers it to
    parse the JSON it would then reject field by field.

    A missing `Content-Length` means a chunked upload, whose size is not knowable
    in advance. That is out of scope here and is bounded instead by the reverse
    proxy in front — noted rather than silently assumed safe.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_request_bytes:
        logger.warning("rejected an oversized request: %s bytes to %s", declared, request.url.path)
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds {settings.max_request_bytes} bytes."},
        )
    return await call_next(request)


# Health + sanitized status at the root; data and intelligence APIs under /api/v1.
app.include_router(health_router)
app.include_router(data_router, prefix=settings.api_v1_prefix)
app.include_router(ai_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": "EconRadar API",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }
