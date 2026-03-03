"""
Credential encryption using Fernet symmetric encryption.

The FERNET_KEY env var is the only thing that can decrypt stored credentials.
It is never written to the database — store it securely and back it up separately.

Generate a new key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet

from app.config import get_settings


def _get_fernet() -> Fernet:
    settings = get_settings()
    return Fernet(settings.fernet_key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns a base64-encoded ciphertext string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a ciphertext string produced by encrypt()."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
