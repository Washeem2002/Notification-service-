import random
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass


class TransientProviderError(Exception):
    pass


class PermanentProviderError(Exception):
    pass


@dataclass(frozen=True)
class Message:
    notification_id: uuid.UUID
    recipient: str
    subject: str | None
    body: str


class Provider(ABC):
    channel: str

    def __init__(self, failure_rate: float = 0.0) -> None:
        self.failure_rate = failure_rate

    def maybe_fail(self) -> None:
        if self.failure_rate and random.random() < self.failure_rate:
            raise TransientProviderError("simulated provider outage")

    @abstractmethod
    async def send(self, message: Message) -> str: ...
