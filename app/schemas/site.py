from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    application_password: str = Field(min_length=1, max_length=255)
    contact_form_id: Optional[int] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v.rstrip("/")


class SiteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    url: Optional[str] = Field(default=None, min_length=1, max_length=255)
    username: Optional[str] = Field(default=None, min_length=1, max_length=255)
    application_password: Optional[str] = Field(default=None, min_length=1, max_length=255)
    contact_form_id: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v.startswith(("http://", "https://")):
                raise ValueError("URL must start with http:// or https://")
            return v.rstrip("/")
        return v


class SiteResponse(BaseModel):
    id: int
    name: str
    url: str
    is_active: bool
    last_synced_at: Optional[datetime] = None
    contact_form_id: Optional[int] = None

    class Config:
        from_attributes = True


class SiteAdminResponse(SiteResponse):
    """Extended response for admin that includes username and timestamps."""
    username: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SiteSyncResponse(BaseModel):
    site_id: int
    forms_found: int
    submissions_synced: int
    status: str
    message: str
