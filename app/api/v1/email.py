import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api import deps
from app import models, schemas
from app.core.config import settings
from app.services.gmail import get_gmail_client_from_db, strip_quoted_text
from app.services.email_templates import build_initial_reply_email, build_admin_reply_email

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_gmail_client(db: Session):
    """Get Gmail client or raise if not configured."""
    if not settings.GMAIL_SENDER_EMAIL:
        raise HTTPException(
            status_code=500,
            detail="Gmail not configured. Set GMAIL_SENDER_EMAIL."
        )

    client = get_gmail_client_from_db(db, settings.GMAIL_SENDER_EMAIL)
    if not client:
        raise HTTPException(
            status_code=500,
            detail="Gmail OAuth not completed. Run OAuth authorization flow first."
        )
    return client


@router.post("/", response_model=schemas.EmailResponse, status_code=201)
def create_email(
    email_in: schemas.EmailCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Send an email for a submission using Gmail API.

    - If no gmail_thread_id exists on submission: this is the FIRST email (starts thread)
      - Subject is REQUIRED
      - Uses build_initial_reply_email with admin's message + "Your message:" + form content
    - If gmail_thread_id exists: this is a FOLLOW-UP email
      - Subject auto-generated as "Re: {first_email_subject}"
      - Uses build_admin_reply_email with just the admin's message
    """
    # 1. Look up the submission
    submission = (
        db.query(models.Submission)
        .filter(models.Submission.id == email_in.submission_id)
        .first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if not submission.submitter_email:
        raise HTTPException(
            status_code=422,
            detail="Submission has no submitter email address",
        )

    # 2. Determine if this is the first email or a follow-up
    is_first_email = not submission.gmail_thread_id

    if is_first_email:
        # FIRST EMAIL - start thread
        if not email_in.subject:
            raise HTTPException(
                status_code=422,
                detail="Subject is required for the first email"
            )
        subject = f"Re: {email_in.subject} Ticket: #{submission.id}"
        html_body = build_initial_reply_email(
            admin_message=email_in.body,
            form_message=submission.message,
            name=submission.submitter_name,
            ticket_id=submission.id
        )
        thread_id = None
        in_reply_to = None
        references = None
    else:
        # FOLLOW-UP EMAIL - use existing thread
        # Get the first email in the thread to use its subject
        first_email = (
            db.query(models.EmailThread)
            .filter(models.EmailThread.submission_id == email_in.submission_id)
            .filter(models.EmailThread.gmail_thread_id.isnot(None))
            .order_by(models.EmailThread.created_at.asc())
            .first()
        )

        if first_email and first_email.subject:
            # Strip any existing "Re: " prefix to avoid "Re: Re: ..."
            original_subject = first_email.subject
            if original_subject.startswith("Re: "):
                original_subject = original_subject[4:]
            # Strip existing "Ticket: #X" suffix if present
            clean_subject = re.sub(r'\s*Ticket:\s*#\d+$', '', original_subject)
            subject = f"Re: {clean_subject} Ticket: #{submission.id}"
        else:
            # Fallback if no first email found
            subject = f"Re: {submission.subject or 'Your inquiry'} Ticket: #{submission.id}"

        # Get the last message for In-Reply-To header (use message_id which is RFC 2822 Message-ID)
        last_email = (
            db.query(models.EmailThread)
            .filter(models.EmailThread.submission_id == email_in.submission_id)
            .filter(models.EmailThread.message_id.isnot(None))
            .filter(models.EmailThread.message_id.like("<%"))  # Only RFC 2822 format Message-IDs
            .order_by(models.EmailThread.created_at.desc())
            .first()
        )

        # Build References header from all previous messages in thread
        all_thread_emails = (
            db.query(models.EmailThread)
            .filter(models.EmailThread.submission_id == email_in.submission_id)
            .filter(models.EmailThread.message_id.isnot(None))
            .filter(models.EmailThread.message_id.like("<%"))  # Only RFC 2822 format Message-IDs
            .order_by(models.EmailThread.created_at.asc())
            .all()
        )
        references_list = [e.message_id for e in all_thread_emails if e.message_id]
        references = " ".join(references_list) if references_list else None

        in_reply_to = last_email.message_id if last_email else None
        thread_id = submission.gmail_thread_id
        
        html_body = build_admin_reply_email(email_in.body, ticket_id=submission.id)

    # 3. Build the email record (message_id will be updated after send with RFC 2822 Message-ID)
    to_email = submission.submitter_email
    from_email = settings.GMAIL_SENDER_EMAIL

    email = models.EmailThread(
        submission_id=email_in.submission_id,
        user_id=current_user.id,
        direction=email_in.direction,
        subject=subject,
        body=email_in.body,  # Store original body, not HTML
        message_id=None,  # Will be set after send with RFC 2822 Message-ID
        to_email=to_email,
        from_email=from_email,
        status=None,
    )

    # 4. For outbound, send via Gmail API
    if email_in.direction == "outbound":
        gmail_client = _get_gmail_client(db)

        logger.info(
            "Email endpoint: is_first=%s, submission.gmail_thread_id=%s, thread_id=%s, in_reply_to=%s, references=%s",
            is_first_email, submission.gmail_thread_id, thread_id, in_reply_to, references
        )

        result = gmail_client.send_email(
            to=to_email,
            subject=subject,
            body=html_body,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references
        )

        if result["success"]:
            gmail_data = result["data"]
            email.status = "sent"
            email.gmail_message_id = gmail_data.get("id")
            email.gmail_thread_id = gmail_data.get("threadId")
            # Store the RFC 2822 Message-ID for threading
            email.message_id = gmail_data.get("message_id_header")

            # Update submission thread_id if not set (first email)
            if not submission.gmail_thread_id:
                submission.gmail_thread_id = gmail_data.get("threadId")
        else:
            logger.error(
                "Gmail send failed to %s for submission %s: %s",
                to_email, email_in.submission_id, result.get("error")
            )
            email.status = "failed"
            # Generate a fallback message_id for failed emails
            email.message_id = str(uuid.uuid4())

    # 5. Always persist to DB (even on failure, so there's a record)
    try:
        db.add(email)
        db.commit()
        db.refresh(email)
    except Exception:
        db.rollback()
        logger.exception("Failed to save email record")
        raise HTTPException(status_code=500, detail="Failed to save email record")

    # 6. If sending failed, inform the caller
    if email.status == "failed":
        raise HTTPException(
            status_code=502,
            detail="Email recorded but delivery failed. Check Gmail configuration.",
        )

    logger.info(
        "Email %s (status=%s) created for submission %s, to=%s, gmail_thread_id=%s, is_first=%s, message_id=%s",
        email.id, email.status, email.submission_id, to_email, email.gmail_thread_id, is_first_email, email.message_id,
    )
    return email


@router.get("/", response_model=List[schemas.EmailResponse])
def list_emails(
    submission_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    emails = (
        db.query(models.EmailThread)
        .filter_by(submission_id=submission_id)
        .order_by(models.EmailThread.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    logger.info(f"Fetched {len(emails)} emails for submission {submission_id}")
    return emails

@router.post("/sync-gmail")
def sync_gmail_inbox(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Manually trigger Gmail inbox sync to fetch customer replies.

    Matches emails by:
    1. Gmail thread ID (primary)
    2. Ticket number in subject like "Ticket: #10" (fallback)
    """
    gmail_client = _get_gmail_client(db)

    # List unread messages
    unread_messages = gmail_client.list_unread_messages(max_results=50)
    logger.info(f"Gmail sync: Found {len(unread_messages)} unread messages")

    processed = 0
    matched = 0

    for msg_brief in unread_messages:
        msg_id = msg_brief.get("id")
        thread_id = msg_brief.get("threadId")

        if not msg_id:
            continue

        processed += 1

        # Check if we already have this message
        existing = db.query(models.EmailThread).filter(
            models.EmailThread.gmail_message_id == msg_id
        ).first()

        if existing:
            continue

        # Fetch full message details
        msg_result = gmail_client.get_message(msg_id)
        if not msg_result["success"]:
            logger.error(f"Failed to fetch message {msg_id}: {msg_result.get('error')}")
            continue

        msg_data = msg_result["data"]

        # Extract sender email
        from_header = msg_data.get("from", "")
        from_email = from_header
        if "<" in from_header and ">" in from_header:
            from_email = from_header.split("<")[1].split(">")[0]

        # Skip if this is from us (outbound email)
        if from_email.lower() == settings.GMAIL_SENDER_EMAIL.lower():
            gmail_client.mark_as_read(msg_id)
            continue

        # Try to match submission by thread_id first
        submission = None
        if thread_id:
            submission = db.query(models.Submission).filter(
                models.Submission.gmail_thread_id == thread_id
            ).first()

        # Fallback: match by ticket number in subject
        if not submission:
            subject = msg_data.get("subject", "")
            ticket_match = re.search(r'Ticket:\s*#(\d+)', subject)
            if ticket_match:
                ticket_id = int(ticket_match.group(1))
                submission = db.query(models.Submission).filter(
                    models.Submission.id == ticket_id
                ).first()
                logger.info(f"Matched email to submission {ticket_id} via ticket number in subject")

        if not submission:
            # Not one of our tracked conversations
            continue

        # Get body and optionally strip quoted text
        raw_body = msg_data.get("body", "")
        is_html = raw_body.strip().startswith('<') or '<div' in raw_body or '<html' in raw_body.lower()
        logger.info(f"Raw body: is_html={is_html}, length={len(raw_body)}, first 300 chars: {raw_body[:300] if raw_body else 'EMPTY'}")

        # If HTML, extract text content first
        if is_html:
            import re as regex
            # Convert block elements and <br> to newlines BEFORE stripping tags
            text_body = raw_body
            text_body = regex.sub(r'<br\s*/?>', '\n', text_body, flags=regex.IGNORECASE)
            text_body = regex.sub(r'</div>', '\n', text_body, flags=regex.IGNORECASE)
            text_body = regex.sub(r'</p>', '\n', text_body, flags=regex.IGNORECASE)
            text_body = regex.sub(r'<div[^>]*class="gmail_quote[^>]*>.*', '', text_body, flags=regex.IGNORECASE | regex.DOTALL)
            # Remove remaining HTML tags
            text_body = regex.sub(r'<[^>]+>', '', text_body)
            # Decode HTML entities
            text_body = text_body.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            # Clean up multiple newlines
            text_body = regex.sub(r'\n{3,}', '\n\n', text_body)
            logger.info(f"Text after HTML conversion: {text_body[:200] if text_body else 'EMPTY'}")
            clean_body = strip_quoted_text(text_body)
        else:
            clean_body = strip_quoted_text(raw_body)

        logger.info(f"Clean body length: {len(clean_body)}, content: {clean_body[:200] if clean_body else 'EMPTY'}")
        # Use raw body only if stripping removed everything AND it's not HTML
        final_body = clean_body if clean_body.strip() else (raw_body if not is_html else "")
        logger.info(f"Final body length: {len(final_body)}")

        # Create email thread record for the inbound reply
        email_thread = models.EmailThread(
            submission_id=submission.id,
            user_id=None,
            direction="inbound",
            subject=msg_data.get("subject"),
            body=final_body,
            message_id=msg_data.get("message_id_header"),
            to_email=settings.GMAIL_SENDER_EMAIL,
            from_email=from_email,
            status="received",
            gmail_message_id=msg_id,
            gmail_thread_id=thread_id,
        )

        db.add(email_thread)

        # Mark submission as 'in_progress' when customer replies
        submission.status = "in_progress"
        submission.has_customer_reply = True
        submission.updated_at = datetime.now(timezone.utc)

        # Mark Gmail message as read
        gmail_client.mark_as_read(msg_id)

        matched += 1
        logger.info(f"Saved inbound reply for submission {submission.id}, gmail_message_id={msg_id}")

    db.commit()

    result = {
        "status": "success",
        "processed": processed,
        "new_emails": matched
    }
    logger.info(f"Gmail sync completed: {result}")
    return result
