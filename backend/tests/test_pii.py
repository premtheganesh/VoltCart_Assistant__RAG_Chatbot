import pytest

from app.guardrails.pii import luhn_valid, redact


@pytest.mark.parametrize(
    ("text", "kinds", "removed"),
    [
        ("My card number is 4111 1111 1111 1111, did it go through?", ["card"], "4111"),
        ("card 5555-5555-5555-4444 exp 12/28", ["card"], "5555"),
        ("amex 378282246310005", ["card"], "378282246310005"),
        ("My SSN is 123-45-6789 for VoltPay", ["ssn"], "6789"),
        ("cvv: 123", ["cvv"], "123"),
    ],
)
def test_sensitive_numbers_are_removed(text, kinds, removed):
    result = redact(text)
    assert result.found == kinds
    assert removed not in result.text and "REMOVED]" in result.text


@pytest.mark.parametrize(
    "text",
    [
        "Order VC-10003, email maya.patel@example.com",  # needed for verification
        "UPS tracking 1Z0000821970820395, FedEx 790757033266",  # fails the Luhn check
        "USPS 9400000000503014435550",
        "Call 1-800-555-0199",
        "The Nova X costs $899 and has 5,000 mAh",
        "VoltBook Pro 16 with 32 GB, 3200x2000 display",
    ],
)
def test_needed_or_harmless_numbers_are_kept(text):
    result = redact(text)
    assert result.found == [] and result.text == text


def test_luhn():
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
