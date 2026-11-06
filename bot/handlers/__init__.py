from .start import router as start_router
from .purchase import router as purchase_router
from .profile import router as profile_router
from .instructions import router as instructions_router
from .admin import router as admin_router

routers = [
    start_router,
    purchase_router,
    profile_router,
    instructions_router,
    admin_router,
]