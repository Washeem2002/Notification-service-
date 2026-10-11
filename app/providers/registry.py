from app.core.config import Settings
from app.providers.base import Provider
from app.providers.email import EmailProvider
from app.providers.push import PushProvider
from app.providers.sms import SmsProvider


def build_providers(settings: Settings) -> dict[str, Provider]:
    rate = settings.provider_failure_rate
    return {
        "email": EmailProvider(settings),
        "sms": SmsProvider(rate),
        "push": PushProvider(rate),
    }
