"""
Waha WhatsApp HTTP API client.
"""
import base64
import logging
import time
from pathlib import Path

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)


class WahaClient:
    def __init__(self):
        settings = get_settings()
        self.base_url = settings.waha_url.rstrip("/")
        self.session = settings.waha_session
        self.headers = {}
        if settings.waha_api_key:
            self.headers["X-Api-Key"] = settings.waha_api_key

    def send_text(self, chat_id: str, text: str) -> dict:
        url = f"{self.base_url}/api/sendText"
        payload = {"chatId": chat_id, "text": text, "session": self.session}
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.error(f"WA send_text failed to {chat_id}: {e}")
            return {}

    def send_document(self, chat_id: str, file_path: str, caption: str = "") -> dict:
        url = f"{self.base_url}/api/sendFile"
        path = Path(file_path)
        with open(path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode()
        payload = {
            "chatId": chat_id, "session": self.session, "caption": caption,
            "file": {"mimetype": "application/pdf", "filename": path.name, "data": file_data},
        }
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.error(f"WA send_document failed to {chat_id}: {e}")
            return {}

    def delete_message(self, chat_id: str, message_id: str) -> bool:
        url = f"{self.base_url}/api/{self.session}/chats/{chat_id}/messages/{message_id}"
        try:
            r = requests.delete(url, headers=self.headers, timeout=10)
            if r.status_code in (200, 204):
                logger.info(f"Deleted message {message_id} in {chat_id}")
                return True
            logger.warning(f"delete_message got {r.status_code} for {message_id}: {r.text[:200]}")
            return False
        except requests.RequestException as e:
            logger.warning(f"delete_message failed for {message_id}: {e}")
            return False

    def resolve_phone(self, jid: str) -> str:
        if "@c.us" in jid:
            return jid.replace("@c.us", "")
        if "@lid" in jid:
            try:
                url = f"{self.base_url}/api/contacts"
                r = requests.get(url, params={"session": self.session, "contactId": jid}, headers=self.headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    number = data.get("number") or data.get("id", "")
                    return number.replace("@c.us", "").replace("+", "")
            except Exception as e:
                logger.warning(f"Could not resolve @lid {jid}: {e}")
            return jid.replace("@lid", "")
        return jid.split("@")[0]


    def download_media(self, message_id: str) -> bytes | None:
        """Download media (image/document) from a received message."""
        url = f"{self.base_url}/api/{self.session}/messages/{message_id}/download"
        try:
            r = requests.get(url, headers=self.headers, timeout=30)
            if r.status_code == 200:
                return r.content
            logger.warning(f"download_media got {r.status_code} for {message_id}")
            return None
        except requests.RequestException as e:
            logger.error(f"download_media failed for {message_id}: {e}")
            return None

    def download_media_url(self, media_url: str) -> bytes | None:
        """Download media directly from a WAHA media URL (payload.media.url).

        WAHA serves media files at /api/files/<filename>. The URL in the
        webhook payload may reference localhost or the container hostname,
        so we extract just the path and prepend our configured base_url.
        """
        from urllib.parse import urlparse
        try:
            path = urlparse(media_url).path
            url = f"{self.base_url}{path}"
            logger.debug(f"download_media_url: {url}")
            r = requests.get(url, headers=self.headers, timeout=30)
            if r.status_code == 200:
                return r.content
            logger.warning(f"download_media_url got {r.status_code} for {url}")
            return None
        except requests.RequestException as e:
            logger.error(f"download_media_url failed for {media_url}: {e}")
            return None

    def get_group_participants(self, group_id: str) -> list[str]:
        """Get participant JIDs for a WhatsApp group."""
        url = f"{self.base_url}/api/{self.session}/groups"
        try:
            r = requests.get(url, headers=self.headers, timeout=15)
            if r.status_code == 200:
                groups = r.json()
                for g in groups:
                    gid = g.get("id", "")
                    if gid == group_id:
                        return [
                            p.get("id", "") for p in g.get("participants", [])
                        ]
            return []
        except requests.RequestException as e:
            logger.error(f"get_group_participants failed for {group_id}: {e}")
            return []

    def send_image(self, chat_id: str, image_data: bytes, caption: str = "") -> dict:
        """Send an image to a chat."""
        url = f"{self.base_url}/api/sendFile"
        import base64 as b64mod
        encoded = b64mod.b64encode(image_data).decode()
        payload = {
            "chatId": chat_id,
            "session": self.session,
            "caption": caption,
            "file": {
                "mimetype": "image/jpeg",
                "filename": "image.jpg",
                "data": encoded,
            },
        }
        try:
            r = requests.post(url, json=payload, headers=self.headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.error(f"WA send_image failed to {chat_id}: {e}")
            return {}
