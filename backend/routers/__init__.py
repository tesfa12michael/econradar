"""FastAPI routers."""

from routers.ai import router as ai_router
from routers.data import router as data_router
from routers.health import router as health_router

__all__ = ["ai_router", "data_router", "health_router"]
