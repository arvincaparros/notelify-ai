from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.config import get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(
    title="Notelify AI API",
    version="0.1.0",
    # No OpenAPI customization yet -- Phase 0 scaffolding only. Endpoint
    # contracts (docs/05-API-CONTRACTS.md) are implemented starting Phase 1.
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health_router)
