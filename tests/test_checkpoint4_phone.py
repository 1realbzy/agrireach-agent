"""Ghana mobile numbers for the farmer form. Fictional subscribers only."""
import pytest

from agrireach.phone import PhoneError, mask_phone, normalize, to_local


FICTIONAL = "0240000001"


def test_local_international_and_trunk_forms_normalize():
    expected = "+233240000001"
    assert normalize(FICTIONAL) == expected
    assert normalize("024 000 0001") == expected
    assert normalize("024-000-0001") == expected
    assert normalize("+233 24 000 0001") == expected
    assert normalize("233240000001") == expected
    assert normalize("00233240000001") == expected
    assert normalize("240000001") == expected
    assert to_local(expected) == FICTIONAL


def test_allocated_mobile_prefixes_are_accepted():
    for local in ("0200000002", "0230000003", "0250000004", "0260000005", "0270000006",
                  "0280000007", "0500000008", "0530000009", "0540000010", "0550000011",
                  "0560000012", "0570000013", "0580000014", "0590000015"):
        assert normalize(local).startswith("+233")
        assert len(normalize(local)) == 13


def test_invalid_numbers_are_rejected_without_echoing_the_input():
    for raw in ("", "   ", "hello", "12345", "024000000", "02400000011", "+2330240000001",
                "0302000001", "+233302000001", "0290000001", "+233290000001", "+2348000000000",
                "0800000001", "0700000001", "+2332400000019"):
        with pytest.raises(PhoneError) as caught:
            normalize(raw)
        if raw.strip():
            assert raw.strip() not in str(caught.value)
        assert "Ghana mobile number" in str(caught.value)


def test_mask_keeps_two_digits():
    assert mask_phone("+233240000001") == "***********01"
    assert "240000001" not in mask_phone("+233240000001")
