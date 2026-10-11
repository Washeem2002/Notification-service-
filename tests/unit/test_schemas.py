import pytest
from pydantic import ValidationError

from app.schemas.notification import NotificationCreate
from app.services.delivery_service import backoff_delay
from app.services.template_service import render_text


def test_requires_template_or_body() -> None:
    with pytest.raises(ValidationError):
        NotificationCreate(user_id="u", channel="email", recipient="a@b.com")


def test_email_recipient_is_validated_and_normalized() -> None:
    item = NotificationCreate(user_id="u", channel="email", recipient="A@Example.com", body="x")
    assert item.recipient == "A@example.com"
    with pytest.raises(ValidationError):
        NotificationCreate(user_id="u", channel="email", recipient="not-an-email", body="x")


def test_sms_requires_e164() -> None:
    NotificationCreate(user_id="u", channel="sms", recipient="+14155550123", body="x")
    with pytest.raises(ValidationError):
        NotificationCreate(user_id="u", channel="sms", recipient="4155550123", body="x")


def test_backoff_grows_and_is_capped() -> None:
    first = backoff_delay(1, base=2, cap=300)
    fifth = backoff_delay(5, base=2, cap=300)
    huge = backoff_delay(30, base=2, cap=300)
    assert 1 <= first <= 2
    assert 16 <= fifth <= 32
    assert 150 <= huge <= 300


def test_render_text_with_variables() -> None:
    assert render_text("Hi {{ name }}", {"name": "Sam"}) == "Hi Sam"


def test_render_text_missing_variable_fails() -> None:
    from app.core.errors import AppError

    with pytest.raises(AppError):
        render_text("Hi {{ name }}", {})
