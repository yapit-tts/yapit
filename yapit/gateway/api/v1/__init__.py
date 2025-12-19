from yapit.gateway.api.v1.admin import router as admin_router
from yapit.gateway.api.v1.billing import router as billing_router
from yapit.gateway.api.v1.documents import router as documents_router
from yapit.gateway.api.v1.filters import router as filters_router
from yapit.gateway.api.v1.models import router as models_router
from yapit.gateway.api.v1.tts import router as tts_router
from yapit.gateway.api.v1.users import router as users_router

__all__ = ["routers"]
routers = [tts_router, documents_router, models_router, filters_router, users_router, admin_router, billing_router]
