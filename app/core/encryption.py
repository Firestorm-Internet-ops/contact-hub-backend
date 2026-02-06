import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_fernet() -> Fernet:
    """Return a Fernet instance using the app's encryption key."""
    return Fernet(settings.ENCRYPTION_KEY.encode())


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy TypeDecorator that transparently encrypts/decrypts
    string values using Fernet symmetric encryption.

    Stores ciphertext in the database column. Decrypts on read.
    """

    impl = String(1024)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt plaintext before writing to the database."""
        if value is not None:
            f = get_fernet()
            return f.encrypt(value.encode("utf-8")).decode("utf-8")
        return value

    def process_result_value(self, value, dialect):
        """Decrypt ciphertext when reading from the database."""
        if value is not None:
            try:
                f = get_fernet()
                return f.decrypt(value.encode("utf-8")).decode("utf-8")
            except InvalidToken:
                logger.error("Failed to decrypt value — invalid token or corrupted data")
                raise
        return value
