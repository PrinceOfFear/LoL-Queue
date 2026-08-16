import importlib


def test_packages_are_importable():
    for name in (
        "lolqueue",
        "lolqueue.lcu",
        "lolqueue.core",
        "lolqueue.ui",
    ):
        assert importlib.import_module(name) is not None


def test_pyside6_is_available():
    import PySide6

    assert PySide6.__version__.startswith("6.")
