import pytest

from app.phone import InvalidPhone, mask_phone, normalize_e164, normalize_phone


def test_us_phone_normalization() -> None:
    assert normalize_phone("(313) 555-0199") == "+13135550199"
    assert normalize_e164("1-313-555-0199") == "+13135550199"


def test_invalid_phone_is_not_guessed() -> None:
    assert normalize_e164("555") is None
    with pytest.raises(InvalidPhone):
        normalize_phone("555")


def test_phone_masking() -> None:
    assert mask_phone("3135550199") == "***-***-0199"
