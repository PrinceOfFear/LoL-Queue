from lolqueue.ui.widgets.status_ring import format_elapsed


def test_formats_under_a_minute():
    assert format_elapsed(0) == "00:00"
    assert format_elapsed(7) == "00:07"


def test_formats_minutes_and_seconds():
    assert format_elapsed(74) == "01:14"
    assert format_elapsed(600) == "10:00"


def test_truncates_fractions():
    assert format_elapsed(9.9) == "00:09"


def test_negative_clamps_to_zero():
    assert format_elapsed(-3) == "00:00"
