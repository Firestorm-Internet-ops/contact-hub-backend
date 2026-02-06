from pydantic import BaseModel

class LoginLogResponse(BaseModel):
    id: int
    user_id: int | None
    email: str
    ip_address: str
    success: bool
    created_at: datetime

    class Config:
        from_attributes = True
    
class LoginLogList(BaseModel):
    logs: list[LoginLogResponse]
    total: int