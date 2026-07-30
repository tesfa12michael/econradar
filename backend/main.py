"""EconRadar FastAPI application entrypoint.

Run locally:  uvicorn main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
