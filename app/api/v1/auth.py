import logging
import time
from collections import defaultdict
from datetime import timedelta
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.orm import Session

from app.api import deps
from app import models, schemas
from app.core import security
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# M14: Simple in-memory rate limiter for login endpoint
# ---------------------------------------------------------------------------
_login_attempts: dict[str, list[float]] = defaultdict(list)
_lock = Lock()
_MAX_LOGIN_ATTEMPTS = 5
_WINDOW_SECONDS = 300  # 5 minutes


def _check_rate_limit(client_ip: str) -> None:
    """Raise 429 if the client has exceeded the login attempt limit."""
    now = time.monotonic()
    with _lock:
        attempts = _login_attempts[client_ip]
        # Prune attempts outside the window
        _login_attempts[client_ip] = [t for t in attempts if now - t < _WINDOW_SECONDS]
        if len(_login_attempts[client_ip]) >= _MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please try again later.",
            )
        _login_attempts[client_ip].append(now)


def _log_login_attempt(db: Session, email: str, ip_address: str, user_id: int | None, success: bool):
    """Log a login attempt to the database."""
    log_entry = models.LoginLog(
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        success=success,
    )
    db.add(log_entry)
    db.commit()


@router.post("/login/access-token", response_model=schemas.Token)
def login_access_token(
    request: Request,
    db: Session = Depends(deps.get_db),
    form_data: schemas.LoginRequest = Depends(),
):
    """
    OAuth2 compatible endpoint to exchange username and password for tokens.
    """
    logger.info(f"Login attempt for user {form_data.username}")
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        _log_login_attempt(db, form_data.username, client_ip, None, False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        _log_login_attempt(db, form_data.username, client_ip, user.id, False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    # Log successful login
    _log_login_attempt(db, form_data.username, client_ip, user.id, True)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )
    refresh_token = security.create_refresh_token(data={"sub": str(user.id)})
    logger.info(f"User {user.email} logged in successfully, id={user.id}")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=schemas.Token)
def refresh_access_token(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    token: str = Depends(deps.reusable_oauth2),
):
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    """
    logger.info(f"Refresh token request received for user {current_user.email}, id={current_user.id}")
    try:
        payload = security.jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.CRYPT_ALGORITHM]
        )
        token_data = schemas.TokenPayload(**payload)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if token_data.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is not a refresh token",
        )

    user = db.query(models.User).filter(models.User.id == token_data.sub).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    access_token = security.create_access_token(data={"sub": str(user.id)})
    refresh_token = security.create_refresh_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/register", response_model=schemas.UserResponse, status_code=201)
def register_user(
    user_in: schemas.UserCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Register a new user. Admin-only.
    """
    logger.info(f"User registration request received for email {user_in.email}, id={user_in.id}")
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can register new users",
        )

    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    user = models.User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        is_active=True,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=schemas.UserResponse)
def get_current_user_profile(
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Get current authenticated user's profile.
    """
    return current_user


@router.put("/me/email", response_model=schemas.UserResponse)
def update_current_user_email(
    email_update: schemas.EmailUpdateRequest,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Update current user's email. Requires password confirmation.
    """
    # Verify current password
    if not security.verify_password(email_update.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
        )

    # Check if new email is already taken
    existing = db.query(models.User).filter(
        models.User.email == email_update.new_email,
        models.User.id != current_user.id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    current_user.email = email_update.new_email
    db.commit()
    db.refresh(current_user)
    logger.info(f"User {current_user.id} updated email to {email_update.new_email}")
    return current_user


@router.put("/me/password", response_model=schemas.MessageResponse)
def update_current_user_password(
    password_update: schemas.PasswordChangeRequest,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Change current user's password. Requires current password confirmation.
    """
    # Verify current password
    if not security.verify_password(password_update.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect current password",
        )

    # Hash and update new password
    current_user.hashed_password = security.get_password_hash(password_update.new_password)
    db.commit()
    logger.info(f"User {current_user.id} changed password")
    return schemas.MessageResponse(message="Password updated successfully")
