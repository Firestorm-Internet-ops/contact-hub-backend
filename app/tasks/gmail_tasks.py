"""Gmail polling tasks for fetching reply emails."""

import logging
from datetime import datetime, timezone

from celery import shared_task

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Submission, EmailThread, GmailCredentials
from app.services.gmail import get_gmail_client_from_db, strip_quoted_text

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.gmail_tasks.poll_gmail_replies_task")
def poll_gmail_replies_task():
    """
    Poll Gmail for unread messages and match them to submissions by thread_id.

    This task:
    1. Lists unread messages from Gmail inbox
    2. For each message, checks if its threadId matches a submission's gmail_thread_id
    3. If match found: saves the reply as an EmailThread record
    4. Sets submission status to 'in_progress' to flag customer reply
    5. Marks the Gmail message as read
    """
    if not settings.GMAIL_SENDER_EMAIL:
        logger.warning("Gmail not configured, skipping poll")
        return {"status": "skipped", "reason": "GMAIL_SENDER_EMAIL not set"}

    db = SessionLocal()
    try:
        # Get Gmail client
        gmail_client = get_gmail_client_from_db(db, settings.GMAIL_SENDER_EMAIL)
        if not gmail_client:
            logger.warning("Gmail OAuth not completed, skipping poll")
            return {"status": "skipped", "reason": "No Gmail credentials"}

        # List unread messages
        unread_messages = gmail_client.list_unread_messages(max_results=50)
        logger.info(f"Found {len(unread_messages)} unread messages")

        processed = 0
        matched = 0

        for msg_brief in unread_messages:
            msg_id = msg_brief.get("id")
            thread_id = msg_brief.get("threadId")

            if not thread_id:
                continue

            processed += 1

            # Check if this thread belongs to any submission
            submission = db.query(Submission).filter(
                Submission.gmail_thread_id == thread_id
            ).first()

            if not submission:
                # Not one of our tracked threads
                continue

            # Check if we already have this message
            existing = db.query(EmailThread).filter(
                EmailThread.gmail_message_id == msg_id
            ).first()

            if existing:
                # Already processed
                continue

            # Fetch full message details
            msg_result = gmail_client.get_message(msg_id)
            if not msg_result["success"]:
                logger.error(f"Failed to fetch message {msg_id}: {msg_result.get('error')}")
                continue

            msg_data = msg_result["data"]

            # Extract sender email
            from_header = msg_data.get("from", "")
            # Parse "Name <email@example.com>" format
            from_email = from_header
            if "<" in from_header and ">" in from_header:
                from_email = from_header.split("<")[1].split(">")[0]

            # Skip if this is from us (outbound email)
            if from_email.lower() == settings.GMAIL_SENDER_EMAIL.lower():
                # Mark as read since it's our own message
                gmail_client.mark_as_read(msg_id)
                continue

            # Strip quoted text from reply
            raw_body = msg_data.get("body", "")
            clean_body = strip_quoted_text(raw_body)

            # Create email thread record for the inbound reply
            email_thread = EmailThread(
                submission_id=submission.id,
                user_id=None,  # No user since it's from the submitter
                direction="inbound",
                subject=msg_data.get("subject"),
                body=clean_body,
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
            submission.updated_at = datetime.now(timezone.utc)

            # Mark Gmail message as read
            gmail_client.mark_as_read(msg_id)

            matched += 1
            logger.info(
                f"Saved inbound reply for submission {submission.id}, "
                f"gmail_message_id={msg_id}"
            )

        db.commit()

        result = {
            "status": "success",
            "processed": processed,
            "matched": matched
        }
        logger.info(f"Gmail poll completed: {result}")
        return result

    except Exception as e:
        logger.exception("Gmail poll task failed")
        db.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
