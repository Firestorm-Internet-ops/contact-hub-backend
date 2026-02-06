"""Email templates for Gmail integration."""


def build_initial_reply_email(admin_message: str, form_message: str, name: str, ticket_id: int) -> str:
    """
    Build the initial email HTML body sent when an admin first replies to a submission.

    The admin provides the subject separately. This builds only the HTML body with:
    - Admin's custom message first
    - "Your message:" section with the original form content in a grey box

    Args:
        admin_message: The admin's reply message
        form_message: The original message from the form submission
        name: The submitter's name
        ticket_id: The submission ID for reference footer

    Returns:
        HTML formatted email body
    """
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; padding: 20px; }}
        .original-message {{ background-color: #f5f5f5; border-left: 4px solid #ccc; padding: 15px; margin: 20px 0; color: #666; }}
        .ticket-ref {{ color: #666; font-size: 0.9em; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <p>Dear {name or 'Customer'},</p>

        <div style="white-space: pre-wrap;">{admin_message}</div>

        <p style="margin-top: 20px;"><strong>Your message:</strong></p>
        <div class="original-message">
            {form_message or '(No message provided)'}
        </div>

        <p class="ticket-ref">Reference: Ticket #{ticket_id}</p>
    </div>
</body>
</html>
"""

    return html_body


def build_admin_reply_email(body: str, ticket_id: int = None) -> str:
    """
    Build the HTML body for an admin reply email (follow-up emails).

    Args:
        body: The plain text or HTML body from the admin
        ticket_id: Optional ticket ID for reference footer

    Returns:
        HTML formatted email body
    """
    ticket_ref = f'<p style="color: #666; font-size: 0.9em; margin-top: 20px;">Reference: Ticket #{ticket_id}</p>' if ticket_id else ''

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        {body}
        {ticket_ref}
    </div>
</body>
</html>
"""

    return html_body
