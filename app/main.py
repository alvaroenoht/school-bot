import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bot.webhook import router as webhook_router
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
app.include_router(webhook_router)


@app.get("/health")
def health_check():
    """Used by Portainer / ALB health checks."""
    return {"status": "ok"}
