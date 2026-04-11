import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bot.webhook import router as webhook_router
from app.api.admin import admin_router
from app.db.database import engine
from app.db.models import Base
from app.scheduler.jobs import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Starting SchoolBot...")
    Base.metadata.create_all(bind=engine)   # create tables if they don't exist
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("SchoolBot is ready ✅")
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    scheduler.shutdown()
    logger.info("SchoolBot stopped.")


app = FastAPI(title="SchoolBot", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5005",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:5005",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(admin_router, prefix="/api/admin")


@app.get("/health")
def health_check():
    """Used by Portainer / ALB health checks."""
    return {"status": "ok"}
