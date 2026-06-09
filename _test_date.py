"""Direkter Test der is_valid_date-Logik (ohne Import der ganzen Module)."""
import re


def is_valid_date(datum: str, jahr=None) -> bool:
    if not datum:
        return True
    if jahr is not None:
        try:
            jahr_int = int(jahr)
        except (ValueError, TypeError):
            jahr_int = None
        if jahr_int is not None and (jahr_int < 1500 or jahr_int > 1754):
            return False
    match = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', datum)
    if not match:
        return False
    tag_str, monat_str, jahr_str = match.groups()
    try:
        tag = int(tag_str)
        monat = int(monat_str)
        jahr_aus_datum = int(jahr_str)
        if jahr_aus_datum < 1500 or jahr_aus_datum > 1754:
            return False
        if monat < 0 or monat > 12:
            return False
        if tag != 0 and (tag < 1 or tag > 31):
            return False
    except ValueError:
        return False
    return True

tests = [
    ("20.11.1564", "1670", True),
    ("", "1670", True),
    ("20.11.1564", None, True),
    ("20.11.1564", "", True),
    ("20.11.1564", 1670, True),
    ("01.01.1800", "1800", False),
    ("01.01.1800", 1800, False),
    ("20.11.1564", "0", False),
    ("20.11.1564", 0, False),
]

for datum, jahr, expected in tests:
    try:
        result = is_valid_date(datum, jahr)
        status = "OK" if result == expected else f"ERWARTET {expected} ERHALTEN {result}"
        print(f"{status}: is_valid_date({datum!r}, {jahr!r}) = {result}")
    except Exception as e:
        print(f"FEHLER: is_valid_date({datum!r}, {jahr!r}) -> {type(e).__name__}: {e}")
