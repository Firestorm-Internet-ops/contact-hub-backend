from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey
from datetime import datetime, timezone

from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(255))
    entity_type = Column(String(255))
    entity_id = Column(Integer)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class TaskExecution(Base):
    __tablename__ = "task_executions"
    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255), index=True)
    status = Column(String(255), index=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))