import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.bot.webhook import router as webhook_router
from app.db.database import engine, SessionLocal
from app.db import models
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


@app.get("/dl/{code}")
def download_redirect(code: str):
    """Redirect a short link code to a fresh S3 presigned URL."""
    from app.utils.s3_upload import generate_presigned_url
    db = SessionLocal()
    try:
        link = db.query(models.ShortLink).filter_by(code=code).first()
        if not link:
            return {"error": "not found"}
        url = generate_presigned_url(link.s3_key)
        return RedirectResponse(url, status_code=302)
    finally:
        db.close()
