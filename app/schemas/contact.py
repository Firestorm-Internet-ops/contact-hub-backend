from datetime import datetime
from typing import Optional, Dict

from pydantic import BaseModel


class ContactFormEntryResponse(BaseModel):
    id: int
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    # We use a Dict for dynamic form fields since keys vary by form
    data: Dict[str, str | None] = {}
    
    # Or if we want to bubble up common fields like 'email' if we know them
    # email: Optional[str] = None
    
    class Config:
        from_attributes = True


class ContactFormEntriesListResponse(BaseModel):
    form_id: int
    form_title: Optional[str] = None
    entries: list[ContactFormEntryResponse]
    # Pagination metadata from WP response if available
    total: Optional[int] = None
    per_page: Optional[int] = None
    current_page: Optional[int] = None
    last_page: Optional[int] = None
