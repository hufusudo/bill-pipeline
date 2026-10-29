import datetime as dt

import pytest

from bill_pipeline.convert import to_cents, to_time_text, yuan
from bill_pipeline.model import BillError


@pytest.mark.parametrize("value, cents", [
    (29.9, 2990), (1234.56, 123456), (0.07, 7), (40, 4000),
    ("1,234.50", 123450), (" 66.60 ", 6660),
])
def test_to_cents(value, cents):
    assert to_cents(value) == cents


@pytest.mark.parametrize("value", [True, None, float("nan"), "abc", "1.234", 0.001, -5])
def test_to_cents_rejects(value):
    with pytest.raises(BillError):
        to_cents(value)


def test_to_time_text_accepts_datetime_serial_and_text():
    expected = "2026-10-01 12:00:00"
    serial = (dt.datetime(2026, 10, 1, 12) - dt.datetime(1899, 12, 30)).total_seconds() / 86400
    assert to_time_text(dt.datetime(2026, 10, 1, 12)) == expected
    assert to_time_text(serial) == expected
    assert to_time_text(" 2026-10-01 12:00:00 ") == expected


@pytest.mark.parametrize("value", [None, True, "2026/10/01", "昨天"])
def test_to_time_text_rejects(value):
    with pytest.raises(BillError):
        to_time_text(value)


def test_yuan():
    assert yuan(123456) == "1234.56"
    assert yuan(5) == "0.05"
    assert yuan(0) == "0.00"
