"""FastAPI routers."""

from routers.data import router as data_router
from routers.health import router as health_router

__all__ = ["data_router", "health_router"]
