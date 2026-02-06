from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Index, UniqueConstraint, Text

from app.core.database import Base


class Submission(Base):
    __tablename__ = "form_submissions"
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    fluent_form_id = Column(Integer)
    form_id = Column(Integer)
    status = Column(String(255), default="new", index=True)
    data = Column(JSON)
    
    # Parsed contact form fields
    submitter_name = Column(String(255), nullable=True)
    submitter_email = Column(String(255), index=True, nullable=True)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)

    submitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    locked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    gmail_thread_id = Column(String(255), nullable=True, index=True)
    has_customer_reply = Column(Boolean, default=False, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("site_id", "form_id", "fluent_form_id", name="unique_site_form_entry"),
        Index("ix_site_form_entry", "site_id", "form_id", "fluent_form_id"),
    )
