import uuid

from app.core.logging import get_logger
from app.providers.base import Message, PermanentProviderError, Provider

log = get_logger("provider.push")


class PushProvider(Provider):
    channel = "push"

    async def send(self, message: Message) -> str:
        if message.recipient.startswith("invalid"):
            raise PermanentProviderError("device token is not registered")
        self.maybe_fail()
        message_id = f"push-{uuid.uuid4()}"
        log.info("push_sent_simulated", to=message.recipient, id=message_id)
        return message_id
