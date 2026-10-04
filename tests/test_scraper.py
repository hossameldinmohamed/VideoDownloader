import pytest

from fbreels.scraper import _sanitize_name, parse_views


@pytest.mark.parametrize("text, expected", [
    ("845", 845), ("12K", 12000), ("1.2M", 1200000), ("1,5k", 1500), ("3B", 3000000000),
    ("1,234", 1234), ("", None), ("Reel", None), ("0:15", None),
])
def test_parse_views(text, expected):
    assert parse_views(text) == expected


@pytest.mark.parametrize("raw, expected", [
    ("(2) Facebook", ""), ("Facebook", ""), ("(12) Some Page | Facebook", "Some Page"),
    ("Some Page | Facebook", "Some Page"), ("A/B: page", "A_B_ page"),
])
def test_sanitize_name(raw, expected):
    assert _sanitize_name(raw) == expected
