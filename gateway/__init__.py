from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from gateway.config import get_settings
from gateway.db import lifespan_db
from gateway.api.v1 import routers as v1_routers  # __all__ inside collects them


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Yapit Gateway",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan_db,  # startup/shutdown incl. DB
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in v1_routers:  # auto-register
        app.include_router(r)
    return app


app = create_app()
