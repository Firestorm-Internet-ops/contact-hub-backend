import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

from app.core.config import settings

def send_email(to_email: str, subject: str, body: str) -> str:
    """
    Sends an email using the configured SMTP settings.

    Args:
        to_email (str): The recipient's email address.
        subject (str): The subject of the email.
        body (str): The body text of the email.

    Returns:
        str: The Message-ID header of the sent email.

    Raises:
        smtplib.SMTPException: If sending the email fails.
    """
    msg = MIMEMultipart()
    # Construct the 'From' header using the name and email from settings
    msg['From'] = formataddr((settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL))
    msg['To'] = to_email
    msg['Subject'] = subject
    # Generate a Message-ID so we can return it. 
    # (Server-assigned IDs are not easily accessible via standard smtplib.send_message)
    msg['Message-ID'] = make_msgid()

    msg.attach(MIMEText(body, 'plain'))

    # Connect to the SMTP server
    # Note: We use the port from settings, but prompt mentioned 587 specifically. 
    # We assume settings.SMTP_PORT is configured to 587.
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        if settings.SMTP_TLS:
            server.starttls()
        
        server.login(settings.SMTP_EMAIL, settings.SMTP_PASSWORD)
        server.send_message(msg)

    return msg['Message-ID']