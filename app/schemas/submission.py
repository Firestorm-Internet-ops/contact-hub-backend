from pydantic import BaseModel
from typing import Optional, Dict, Any, Literal
from datetime import datetime

# Valid status values for submissions
StatusType = Literal["new", "waiting_internal", "waiting_customer", "in_progress", "closed"]

class SubmissionCreate(BaseModel):
    site_id: int
    fluent_form_id: int
    form_id: int
    status: StatusType = "new"
    data: Dict[str, Any] = {}

class SubmissionResponse(BaseModel):
    id: int
    site_id: int
    fluent_form_id: int
    form_id: int
    status: StatusType
    data: Dict[str, Any]
    submitted_at: datetime
    submitter_name: Optional[str] = None
    submitter_email: Optional[str] = None
    subject: Optional[str] = None
    message: Optional[str] = None
    locked_by: Optional[int] = None
    locked_at: Optional[datetime] = None
    is_active: bool
    gmail_thread_id: Optional[str] = None
    has_customer_reply: bool = False

    class Config:
        from_attributes = True

class SubmissionUpdate(BaseModel):
    status: Optional[StatusType] = None
    is_active: Optional[bool] = None
    locked_by: Optional[int] = None
    locked_at: Optional[datetime] = None