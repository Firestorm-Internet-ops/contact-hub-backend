from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class EmailCreate(BaseModel):
    submission_id: int
    subject: Optional[str] = Field(default=None, max_length=255)
    body: str = Field(max_length=65535)
    direction: Literal["inbound", "outbound"] = "outbound"


class EmailResponse(BaseModel):
    id: int
    submission_id: int
    subject: Optional[str] = None
    body: Optional[str] = None
    direction: str
    to_email: Optional[str] = None
    from_email: Optional[str] = None
    status: Optional[str] = None
    message_id: Optional[str] = None
    user_id: Optional[int] = None
    gmail_message_id: Optional[str] = None
    gmail_thread_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
