from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_phone: str                    # e.g. "50766xxxxxx" (no + or spaces)

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str
    openai_model: str = "gpt-4.1-nano"

    # ── Waha (WhatsApp gateway) ───────────────────────────────────────────────
    waha_url: str = "http://waha:3000"
    waha_session: str = "default"
    waha_api_key: str = ""
    waha_bot_phone: str = ""            # the number linked to waha (no + or spaces)

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql://schoolbot:schoolbot@postgres:5432/schoolbot"

    # ── Encryption ────────────────────────────────────────────────────────────
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str

    # ── Scheduler ─────────────────────────────────────────────────────────────
    timezone: str = "America/Panama"
    sync_time: str = "18:20"           # HH:MM
    summary_day: str = "thursday"
    summary_time: str = "18:30"        # HH:MM
    reminder_time: str = "07:00"       # HH:MM  Mon-Fri

    # ── AWS (Textract for receipt OCR) ──────────────────────────────────────
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
