"""Customer identity.

The rules here decide whether a shop sees one returning customer or three
strangers. Phone normalisation is the whole game: it is the only key that
survives a person moving between channels.
"""
import pytest

from app.services.customer_service import normalize_phone


@pytest.mark.parametrize("raw", [
    "+998 90 123 45 67",
    "998901234567",
    "901234567",
    "+998901234567",
    "8 90 123 45 67",
    "(90) 123-45-67",
    "  +998-90-123-45-67  ",
])
def test_the_same_person_however_they_type_it(raw):
    assert normalize_phone(raw) == "+998901234567"


@pytest.mark.parametrize("raw", [None, "", "   ", "yo'q", "12", "abc-def"])
def test_nothing_dialable_is_no_number(raw):
    """A junk value must not become a customer key — otherwise every lead with
    a typo in the phone field merges into one imaginary person."""
    assert normalize_phone(raw) is None


def test_a_foreign_number_is_kept_as_given():
    assert normalize_phone("+7 999 123 45 67") == "+79991234567"


def test_a_longer_national_number_is_not_mangled():
    """Only a bare 9-digit local number gets the country code added."""
    assert normalize_phone("442071838750") == "+442071838750"
