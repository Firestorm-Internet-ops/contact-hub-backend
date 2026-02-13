"""Gmail OAuth endpoints for authorization flow."""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.api import deps
from app import models
from app.core.config import settings
from app.services.gmail import save_gmail_credentials

logger = logging.getLogger(__name__)

router = APIRouter()


def get_oauth_flow() -> Flow:
    """Create and return a Google OAuth flow instance."""
    client_config = {
        "web": {
            "client_id": settings.GMAIL_CLIENT_ID,
            "client_secret": settings.GMAIL_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GMAIL_REDIRECT_URI],
        }
    }

    scopes = settings.GMAIL_SCOPES.split()

    flow = Flow.from_client_config(
        client_config,
        scopes=scopes,
        redirect_uri=settings.GMAIL_REDIRECT_URI
    )

    return flow


@router.get("/oauth/authorize")
def gmail_oauth_authorize(
    current_user: models.User = Depends(deps.get_current_admin_user),
):
    """
    Initiates the Gmail OAuth authorization flow.
    Returns the Google OAuth URL that the admin should visit.
    Admin-only endpoint.
    """
    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Gmail OAuth not configured. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET."
        )

    flow = get_oauth_flow()

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    logger.info(f"Gmail OAuth initiated by user {current_user.id}")

    return {
        "authorization_url": authorization_url,
        "state": state,
        "message": "Redirect user to authorization_url to complete OAuth flow"
    }


@router.get("/oauth/callback")
def gmail_oauth_callback(
    code: str = Query(None, description="Authorization code from Google"),
    state: str = Query(None, description="State parameter for CSRF protection"),
    error: str = Query(None, description="Error from OAuth flow"),
    db: Session = Depends(deps.get_db),
):
    """
    Handles the OAuth callback from Google.
    Exchanges the authorization code for tokens and saves them to the database.
    """
    if error:
        logger.error(f"Gmail OAuth error: {error}")
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        return RedirectResponse(url=f"{frontend_url}/settings?gmail_error={error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        flow = get_oauth_flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get the user's email from the ID token or use configured sender email
        user_email = settings.GMAIL_SENDER_EMAIL

        if not user_email:
            # Try to get email from credentials if possible
            # For now, we'll require GMAIL_SENDER_EMAIL to be set
            raise HTTPException(
                status_code=500,
                detail="GMAIL_SENDER_EMAIL must be configured"
            )

        # Save credentials to database
        save_gmail_credentials(
            db=db,
            email=user_email,
            credentials=credentials,
            client_secret=settings.GMAIL_CLIENT_SECRET
        )

        logger.info(f"Gmail OAuth credentials saved for {user_email}")

        frontend_url = settings.FRONTEND_URL.rstrip("/")
        return RedirectResponse(url=f"{frontend_url}/settings")

    except Exception as e:
        logger.exception("Gmail OAuth callback error")
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        error_msg = str(e).replace(" ", "+")
        return RedirectResponse(url=f"{frontend_url}/settings?gmail_error={error_msg}")


@router.get("/status")
def gmail_oauth_status(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin_user),
):
    """
    Check if Gmail OAuth credentials are configured and valid.
    Admin-only endpoint.
    """
    if not settings.GMAIL_SENDER_EMAIL:
        return {
            "configured": False,
            "message": "GMAIL_SENDER_EMAIL not set"
        }

    cred_record = db.query(models.GmailCredentials).filter(
        models.GmailCredentials.user_email == settings.GMAIL_SENDER_EMAIL
    ).first()

    if not cred_record:
        return {
            "configured": False,
            "email": settings.GMAIL_SENDER_EMAIL,
            "message": "No OAuth credentials found. Run OAuth authorization flow."
        }

    return {
        "configured": True,
        "email": cred_record.user_email,
        "expiry": cred_record.expiry.isoformat() if cred_record.expiry else None,
        "updated_at": cred_record.updated_at.isoformat() if cred_record.updated_at else None
    }
