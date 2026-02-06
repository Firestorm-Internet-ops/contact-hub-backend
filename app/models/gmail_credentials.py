from sqlalchemy import Column, Integer, String, DateTime
from app.core.database import Base
from app.core.encryption import EncryptedString
from datetime import datetime, timezone

class GmailCredentials(Base):
    __tablename__ = "gmail_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String(255), unique=True, index=True, nullable=False)
    
    # OAuth tokens (encrypted)
    access_token = Column(EncryptedString, nullable=False)
    refresh_token = Column(EncryptedString, nullable=False)
    client_secret = Column(EncryptedString, nullable=False)
    
    # Other metadata
    token_uri = Column(String(255), nullable=False)
    client_id = Column(String(255), nullable=False)
    scopes = Column(String(255), nullable=False)
    expiry = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))