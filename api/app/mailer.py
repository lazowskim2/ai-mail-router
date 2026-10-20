import smtplib
from email.message import EmailMessage

from .config import settings


def _connect() -> smtplib.SMTP:
    if settings.smtp_security == "ssl":
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        if settings.smtp_security == "starttls":
            smtp.starttls()
    if settings.smtp_user:
        smtp.login(settings.smtp_user, settings.smtp_password)
    return smtp


def send_department_email(to: str, subject: str, body: str, reply_to: str) -> None:
    """Send the routed message to `to`, with Reply-To deterministically set to
    the original sender's address (never taken from the model's output)."""

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)

    with _connect() as smtp:
        smtp.send_message(msg)
