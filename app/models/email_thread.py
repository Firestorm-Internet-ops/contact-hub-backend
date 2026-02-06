from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, CheckConstraint

from app.core.database import Base


class EmailThread(Base):
    __tablename__ = "email_threads"
    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    direction = Column(String(10), nullable=False, index=True)
    subject = Column(String(255), nullable=True)
    body = Column(Text)
    message_id = Column(String(255), unique=True, index=True)
    to_email = Column(String(255), nullable=True)
    from_email = Column(String(255), nullable=True)
    status = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    gmail_message_id = Column(String(255), nullable=True, unique=True, index=True)
    gmail_thread_id = Column(String(255), nullable=True, index=True)

    __table_args__ = (
        CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_email_threads_direction"),
    )
