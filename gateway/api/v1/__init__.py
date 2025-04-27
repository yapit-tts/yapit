from gateway.api.v1.documents import router as documents_router
from gateway.api.v1.tts import router as tts_router

__all__ = ["routers"]
routers = [tts_router, documents_router]
