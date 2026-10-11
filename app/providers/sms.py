import uuid

from app.core.logging import get_logger
from app.providers.base import Message, Provider

log = get_logger("provider.sms")


class SmsProvider(Provider):
    channel = "sms"

    async def send(self, message: Message) -> str:
        self.maybe_fail()
        message_id = f"sms-{uuid.uuid4()}"
        log.info("sms_sent_simulated", to=message.recipient, id=message_id)
        return message_id
