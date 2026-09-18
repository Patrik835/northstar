from email.message import EmailMessage
from email.utils import formataddr
from html import escape

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
        await self._send(message)

    async def send_notification_digest(
        self,
        *,
        recipient: str,
        username: str,
        alerts: list[str],
        news: list[str],
        events: list[str],
        updates_url: str,
    ) -> None:
        message = EmailMessage()
        message["From"] = formataddr(
            (self.settings.email_from_name, self.settings.email_from_address)
        )
        message["To"] = recipient
        message["Subject"] = "Your Northstar update"
        sections = []
        for heading, items in (("Needs attention", alerts), ("Upcoming", events), ("News", news)):
            if items:
                sections.append(f"{heading}:\n" + "\n".join(f"- {item}" for item in items))
        body = "\n\n".join(sections) or "Nothing new needs your attention."
        message.set_content(
            f"Hello {username},\n\n{body}\n\nOpen Northstar: {updates_url}\n\n"
            "Informational and educational only—not financial advice."
        )
        html_sections = "".join(
            f"<h3>{escape(heading)}</h3><ul>"
            f"{''.join(f'<li>{escape(item)}</li>' for item in items)}</ul>"
            for heading, items in (
                ("Needs attention", alerts),
                ("Upcoming", events),
                ("News", news),
            )
            if items
        )
        message.add_alternative(
            f"""
            <html><body style="font-family:Arial,sans-serif;color:#14231d">
              <h2>Your Northstar update</h2><p>Hello {escape(username)},</p>{html_sections}
              <p><a href="{escape(updates_url, quote=True)}">Open updates</a></p>
              <p style="color:#66756e">Informational and educational only—not financial advice.</p>
            </body></html>
            """,
            subtype="html",
        )
        await self._send(message)

    async def send_password_reset_email(
        self,
        *,
        recipient: str,
        username: str,
        reset_url: str,
        expires_minutes: int,
    ) -> None:
        message = EmailMessage()
        message["From"] = formataddr(
            (self.settings.email_from_name, self.settings.email_from_address)
        )
        message["To"] = recipient
        message["Subject"] = "Reset your Northstar password"
        message.set_content(
            f"Hello {username},\n\nReset your Northstar password:\n{reset_url}\n\n"
            f"This link expires in {expires_minutes} minutes and can be used once.\n"
            "If you did not request this, you can ignore this email."
        )
        message.add_alternative(
            f"""
            <html><body style="font-family:Arial,sans-serif;color:#14231d">
              <h2>Reset your password</h2>
              <p>Hello {escape(username)},</p>
              <p><a href="{escape(reset_url, quote=True)}" style="background:#1f7a52;color:white;
              padding:12px 18px;border-radius:6px;text-decoration:none">Reset password</a></p>
              <p>This one-time link expires in {expires_minutes} minutes.</p>
              <p style="color:#66756e">If you did not request this, ignore this email.</p>
            </body></html>
            """,
            subtype="html",
        )
        await self._send(message)

    async def _send(self, message: EmailMessage) -> None:
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
            raise EmailDeliveryError("Email could not be delivered") from exc
