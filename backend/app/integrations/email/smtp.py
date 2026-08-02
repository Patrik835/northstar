from email.message import EmailMessage
from email.utils import formataddr

import aiosmtplib

from app.core.config import Settings
from app.integrations.email.base import EmailDeliveryError, EmailSender


class SMTPEmailSender(EmailSender):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_verification_email(
        self, *, recipient: str, username: str, verification_url: str
    ) -> None:
        message = EmailMessage()
        message["From"] = formataddr(
            (self.settings.email_from_name, self.settings.email_from_address)
        )
        message["To"] = recipient
        message["Subject"] = "Verify your Northstar account"
        message.set_content(
            f"Hello {username},\n\n"
            "Verify your email address to activate your Northstar account:\n"
            f"{verification_url}\n\n"
            f"This link expires in {self.settings.email_verification_ttl_hours} hours.\n"
            "If you did not create this account, you can ignore this email."
        )
        message.add_alternative(
            f"""
            <html><body style="font-family:Arial,sans-serif;color:#14231d">
              <h2>Welcome to Northstar</h2>
              <p>Hello {username},</p>
              <p>Verify your email address to activate your account.</p>
              <p><a href="{verification_url}" style="background:#1f7a52;color:white;
              padding:12px 18px;border-radius:6px;text-decoration:none">Verify email</a></p>
              <p>This link expires in {self.settings.email_verification_ttl_hours} hours.</p>
              <p style="color:#66756e">If you did not create this account, ignore this email.</p>
            </body></html>
            """,
            subtype="html",
        )
        try:
            await aiosmtplib.send(
                message,
                hostname=self.settings.smtp_host,
                port=self.settings.smtp_port,
                username=self.settings.smtp_username,
                password=self.settings.smtp_password,
                start_tls=self.settings.smtp_start_tls,
                use_tls=self.settings.smtp_use_tls,
                timeout=10,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise EmailDeliveryError("Verification email could not be delivered") from exc
