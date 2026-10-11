import uuid
from email.message import EmailMessage

import aiosmtplib

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.base import (
    Message,
    PermanentProviderError,
    Provider,
    TransientProviderError,
)

log = get_logger("provider.email")


class EmailProvider(Provider):
    channel = "email"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.provider_failure_rate)
        self.settings = settings

    async def send(self, message: Message) -> str:
        self.maybe_fail()
        message_id = f"email-{uuid.uuid4()}"
        if not self.settings.smtp_host:
            log.info("email_sent_simulated", to=message.recipient, id=message_id)
            return message_id
        mail = EmailMessage()
        mail["From"] = self.settings.smtp_from
        mail["To"] = message.recipient
        mail["Subject"] = message.subject or ""
        mail["Message-ID"] = f"<{message_id}@notification-service>"
        mail.set_content(message.body)
        try:
            await aiosmtplib.send(
                mail,
                hostname=self.settings.smtp_host,
                port=self.settings.smtp_port,
                username=self.settings.smtp_user or None,
                password=self.settings.smtp_password or None,
                start_tls=True,
                timeout=15,
            )
        except aiosmtplib.SMTPRecipientsRefused as exc:
            raise PermanentProviderError(str(exc)) from exc
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise TransientProviderError(str(exc)) from exc
        return message_id
