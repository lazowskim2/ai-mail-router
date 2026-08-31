import smtplib
from email.message import EmailMessage

from .config import settings


def send_department_email(to: str, subject: str, body: str, reply_to: str) -> None:
    """Send the routed message to `to`, captured by MailHog, with Reply-To
    deterministically set to the original sender's address."""

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(msg)
