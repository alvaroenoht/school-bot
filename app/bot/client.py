"""
Waha WhatsApp HTTP API client.
Docs: https://waha.devlike.pro/docs/how-to/send-messages/
"""
import base64
import logging
import time
from pathlib import Path

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

# WhatsApp character limit (same as Telegram)
WA_MAX_LENGTH = 4000


class WahaClient:
    def __init__(self):
        settings = get_settings()
        self.base_url = settings.waha_url.rstrip("/")
        self.session = settings.waha_session
        self.headers = {}
        if settings.waha_api_key:
            self.headers["X-Api-Key"] = settings.waha_api_key

    # ── Core send methods ──────────────────────────────────────────────────────

    def send_text(self, chat_id: str, text: str) -> dict:
        """Send a plain text message to a WhatsApp chat or group."""
        url = f"{self.base_url}/api/sendText"
        payload = {
            "chatId": chat_id,
            "text": text,
            "session": self.session,
        }
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.error(f"WA send_text failed to {chat_id}: {e}")
            return {}

    def send_document(self, chat_id: str, file_path: str, caption: str = "") -> dict:
        """Send a file (e.g. PDF) to a WhatsApp chat."""
        url = f"{self.base_url}/api/sendFile"
        path = Path(file_path)
        with open(path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode()

        payload = {
            "chatId": chat_id,
            "session": self.session,
            "caption": caption,
            "file": {
                "mimetype": "application/pdf",
                "filename": path.name,
                "data": file_data,
            },
        }
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.error(f"WA send_document failed to {chat_id}: {e}")
            return {}

    # ── Helpers ────────────────────────────────────────────────────────────────

    def resolve_phone(self, jid: str) -> str:
        """
        Resolve a WhatsApp JID to a plain phone number string.
        Handles @c.us (standard) and @lid (linked device) formats.
        Returns digits only, or the raw ID before @ on failure.
        """
        if "@c.us" in jid:
            return jid.replace("@c.us", "")

        if "@lid" in jid:
            try:
                url = f"{self.base_url}/api/contacts/{jid}"
                r = requests.get(url, params={"session": self.session}, headers=self.headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    number = data.get("number") or data.get("id", "")
                    return number.replace("@c.us", "").replace("+", "")
            except Exception as e:
                logger.warning(f"Could not resolve @lid {jid}: {e}")
            return jid.replace("@lid", "")

        return jid.split("@")[0]

    def send_chunked(self, chat_id: str, text: str) -> None:
        """Split and send a long message in chunks (respects WA_MAX_LENGTH)."""
        if len(text) <= WA_MAX_LENGTH:
            self.send_text(chat_id, text)
            return

        chunks: list[str] = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 <= WA_MAX_LENGTH:
                current += line + "\n"
            else:
                chunks.append(current)
                current = line + "\n"
        if current:
            chunks.append(current)

        for i, chunk in enumerate(chunks, 1):
            if len(chunks) > 1:
                chunk = f"*Parte {i}/{len(chunks)}*\n{chunk}"
            self.send_text(chat_id, chunk)
            time.sleep(0.5)   # avoid rate limits
