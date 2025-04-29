from yapit.gateway.api.v1.documents import router as documents_router
from yapit.gateway.api.v1.models import router as models_router
from yapit.gateway.api.v1.tts import router as tts_router

__all__ = ["routers"]
routers = [tts_router, documents_router, models_router]
