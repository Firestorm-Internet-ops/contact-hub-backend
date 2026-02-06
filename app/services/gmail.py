import base64
import logging
import re
import uuid
from email.mime.text import MIMEText
from email.utils import formatdate
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

class GmailClient:
    def __init__(self, credentials):
        """
        Initializes the Gmail API service.
        'credentials' should be a google.oauth2.credentials.Credentials object.
        """
        self.service = build('gmail', 'v1', credentials=credentials)

    def send_email(self, to, subject, body, thread_id=None, in_reply_to=None, references=None):
        """
        Sends an email. Supports threading if thread_id and in_reply_to are provided.
        Returns: {success, data: {id, threadId, message_id_header}, error}

        The message_id_header is the RFC 2822 Message-ID we generate, which should be
        stored and used for In-Reply-To headers on subsequent replies.
        """
        try:
            from app.core.config import settings

            message = MIMEText(body, 'html', 'utf-8')
            message['to'] = to
            message['from'] = settings.GMAIL_SENDER_EMAIL
            message['subject'] = subject
            message['Date'] = formatdate(localtime=True)

            # Generate a proper RFC 2822 Message-ID
            # Use sender's domain to avoid conflicts with Gmail's own Message-IDs
            sender_domain = settings.GMAIL_SENDER_EMAIL.split('@')[1] if '@' in settings.GMAIL_SENDER_EMAIL else 'localhost'
            message_id_header = f"<{uuid.uuid4()}@{sender_domain}>"
            message['Message-ID'] = message_id_header

            # Threading Headers - use proper RFC 2822 Message-ID format
            if in_reply_to:
                message['In-Reply-To'] = in_reply_to
                # References should include the full chain, but at minimum the message being replied to
                message['References'] = references if references else in_reply_to

            # Encode to Base64URL
            raw_bytes = message.as_bytes()
            encoded_message = base64.urlsafe_b64encode(raw_bytes).decode()

            payload = {'raw': encoded_message}
            if thread_id:
                payload['threadId'] = thread_id

            logger.info(
                "Gmail send_email: to=%s, subject=%s, thread_id=%s, in_reply_to=%s, references=%s",
                to, subject, thread_id, in_reply_to, references
            )

            result = self.service.users().messages().send(userId='me', body=payload).execute()
            logger.info("Gmail API response: id=%s, threadId=%s", result.get('id'), result.get('threadId'))

            # Gmail overwrites our Message-ID with its own format.
            # We need to fetch the sent message to get the ACTUAL Message-ID for threading.
            sent_message_id = result.get('id')
            if sent_message_id:
                try:
                    sent_msg = self.service.users().messages().get(
                        userId='me', id=sent_message_id, format='metadata',
                        metadataHeaders=['Message-ID']
                    ).execute()
                    headers = sent_msg.get('payload', {}).get('headers', [])
                    gmail_message_id = next(
                        (h['value'] for h in headers if h['name'].lower() == 'message-id'),
                        None
                    )
                    if gmail_message_id:
                        result['message_id_header'] = gmail_message_id
                        logger.info("Gmail assigned Message-ID: %s", gmail_message_id)
                    else:
                        result['message_id_header'] = message_id_header
                except Exception as e:
                    logger.warning("Failed to fetch Gmail's Message-ID, using local: %s", e)
                    result['message_id_header'] = message_id_header
            else:
                result['message_id_header'] = message_id_header

            return {"success": True, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_unread_messages(self, max_results=50):
        """
        Lists unread messages from the inbox.
        Returns: list of {id, threadId}
        """
        try:
            query = "is:unread label:INBOX"
            response = self.service.users().messages().list(
                userId='me', q=query, maxResults=max_results
            ).execute()
            return response.get('messages', [])
        except Exception as e:
            print(f"Error listing messages: {e}")
            return []

    def get_message(self, message_id):
        """
        Fetches and parses a specific message.
        Returns: {success, data: {id, threadId, message_id_header, subject, body...}, error}
        """
        try:
            msg = self.service.users().messages().get(
                userId='me', id=message_id, format='full'
            ).execute()

            payload = msg.get('payload', {})
            headers = payload.get('headers', [])

            def get_header(name):
                return next((h['value'] for h in headers if h['name'].lower() == name.lower()), None)

            data = {
                "id": msg['id'],
                "threadId": msg['threadId'],
                "message_id_header": get_header('Message-ID'),
                "subject": get_header('Subject'),
                "from": get_header('From'),
                "body": ""
            }

            # Recursive parser for the body
            def parse_parts(parts):
                body = ""
                for part in parts:
                    mime_type = part.get('mimeType')
                    part_body = part.get('body', {}).get('data')
                    if mime_type == 'text/html' and part_body:
                        return base64.urlsafe_b64decode(part_body).decode('utf-8')
                    elif mime_type == 'text/plain' and part_body:
                        body = base64.urlsafe_b64decode(part_body).decode('utf-8')
                    if 'parts' in part:
                        nested = parse_parts(part['parts'])
                        if nested: return nested
                return body

            if 'parts' in payload:
                data['body'] = parse_parts(payload['parts'])
                logger.info(f"get_message: parsed from parts, body length={len(data['body'])}")
            else:
                raw_body = payload.get('body', {}).get('data')
                if raw_body:
                    data['body'] = base64.urlsafe_b64decode(raw_body).decode('utf-8')
                    logger.info(f"get_message: parsed from payload.body, body length={len(data['body'])}")
                else:
                    logger.warning(f"get_message: no body found in payload. mimeType={payload.get('mimeType')}")

            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def mark_as_read(self, message_id):
        """Removes the UNREAD label from a message."""
        try:
            self.service.users().messages().modify(
                userId='me', id=message_id, body={'removeLabelIds': ['UNREAD']}
            ).execute()
            return True
        except Exception as e:
            print(f"Error marking read: {e}")
            return False

# --- Helper Functions ---

def strip_quoted_text(body):
    """Removes the 'On ... wrote:' and reply history from an email body."""
    if not body: return ""
    patterns = [
        r'On\s+.+\s+wrote:',  # "On Thu, Feb 5... wrote:"
        r'---+\s*Original Message\s*---+',
        r'Sent from my (iPhone|Android)',
    ]
    lines = body.splitlines()
    clean_lines = []
    for line in lines:
        # Check if line matches any quote pattern
        if any(re.search(p, line, re.IGNORECASE) for p in patterns):
            logger.info(f"strip_quoted_text: stopping at line: {line[:80]}")
            break
        # Check for quoted lines starting with >
        if line.strip().startswith('>'):
            logger.info(f"strip_quoted_text: stopping at quoted line: {line[:50]}")
            break
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()

def get_gmail_client_from_db(db, email: str):
    """
    Loads credentials from DB, refreshes if needed, and returns GmailClient.

    Args:
        db: SQLAlchemy Session
        email: The Gmail account email address

    Returns:
        GmailClient instance or None if credentials not found
    """
    from app.models import GmailCredentials

    cred_record = db.query(GmailCredentials).filter(
        GmailCredentials.user_email == email
    ).first()

    if not cred_record:
        return None

    scopes = cred_record.scopes.split() if cred_record.scopes else []

    creds = Credentials(
        token=cred_record.access_token,
        refresh_token=cred_record.refresh_token,
        token_uri=cred_record.token_uri,
        client_id=cred_record.client_id,
        client_secret=cred_record.client_secret,
        scopes=scopes
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_gmail_credentials(db, email, creds)

    return GmailClient(creds)


def save_gmail_credentials(db, email: str, credentials, client_secret: str = None):
    """
    Saves or updates Gmail OAuth credentials in the database.

    Args:
        db: SQLAlchemy Session
        email: The Gmail account email address
        credentials: google.oauth2.credentials.Credentials object
        client_secret: Optional client secret (needed for first save)
    """
    from app.models import GmailCredentials
    from datetime import datetime, timezone

    cred_record = db.query(GmailCredentials).filter(
        GmailCredentials.user_email == email
    ).first()

    scopes_str = " ".join(credentials.scopes) if credentials.scopes else ""

    if cred_record:
        # Update existing record
        cred_record.access_token = credentials.token
        if credentials.refresh_token:
            cred_record.refresh_token = credentials.refresh_token
        cred_record.expiry = credentials.expiry
        cred_record.updated_at = datetime.now(timezone.utc)
    else:
        # Create new record
        cred_record = GmailCredentials(
            user_email=email,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            client_secret=client_secret or "",
            token_uri=credentials.token_uri or "https://oauth2.googleapis.com/token",
            client_id=credentials.client_id or "",
            scopes=scopes_str,
            expiry=credentials.expiry
        )
        db.add(cred_record)

    db.commit()
    db.refresh(cred_record)
    return cred_record