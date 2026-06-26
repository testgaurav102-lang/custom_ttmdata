"""
Sales Intel Agent — FastAPI application entry point.

Registers routers, configures CORS, and exposes health-check endpoints.
"""

import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import chat as chat_router
from app.routers import docs as docs_router
from app.routers import files as files_router
from app.routers import metadata as metadata_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_LEVEL = logging.DEBUG if settings.debug else logging.INFO

logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s (debug=%s)", settings.app_name, settings.debug)
    yield
    logger.info("Shutting down %s.", settings.app_name)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Enterprise-grade AI Data Analysis Agent with REST APIs, "
        "DuckDB-powered data ingestion, and Mermaid chart generation."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(metadata_router.router, tags=["Metadata"])
app.include_router(chat_router.router, tags=["Chat"])
app.include_router(files_router.router, tags=["Files"])
app.include_router(docs_router.router, tags=["Docs"])


# ---------------------------------------------------------------------------
# Built-in endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Health"])
async def health():
    """Liveness probe — returns 200 when the application is running."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/", tags=["Health"])
def root():
    return {"status": "healthy", "message": "Application is running"}
