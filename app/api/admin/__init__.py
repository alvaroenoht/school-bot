from fastapi import APIRouter
from app.api.admin.auth import router as auth_router
from app.api.admin.classrooms import router as classrooms_router
from app.api.admin.fundraisers import router as fundraisers_router
from app.api.admin.forms import router as forms_router
from app.api.admin.assistant import router as assistant_router
from app.api.admin.events import router as events_router
from app.api.admin.edulink import router as edulink_router
from app.api.admin.seduca import router as seduca_router
from app.api.admin.students import router as students_router
from app.api.admin.dashboard import router as dashboard_router

admin_router = APIRouter()
admin_router.include_router(auth_router)
admin_router.include_router(classrooms_router)
admin_router.include_router(fundraisers_router)
admin_router.include_router(forms_router)
admin_router.include_router(assistant_router)
admin_router.include_router(events_router)
admin_router.include_router(edulink_router)
admin_router.include_router(seduca_router)
admin_router.include_router(students_router)
admin_router.include_router(dashboard_router)
