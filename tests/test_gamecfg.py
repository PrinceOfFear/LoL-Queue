"""The generic game.cfg reader used by the chat protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from lolqueue.core import gamecfg


CFG = """[General]
EnableChat=1
"""


def _install(root: Path, text: str = CFG) -> Path:
    file = root / gamecfg.CONFIG_SUBPATH
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    return file


@pytest.fixture(autouse=True)
def _without_the_real_machine(monkeypatch):
    monkeypatch.setattr(gamecfg, "_found", None)
    monkeypatch.setattr(gamecfg, "_from_processes", lambda: iter(()))
    monkeypatch.setattr(gamecfg, "_from_drives", lambda: iter(()))
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", ())


def test_nothing_found_is_reported_as_nothing_found():
    assert gamecfg.config_path() is None


def test_the_install_on_another_drive_is_found(tmp_path, monkeypatch):
    expected = _install(tmp_path / "D")
    monkeypatch.setattr(
        gamecfg, "_from_drives", lambda: iter([tmp_path / "C", tmp_path / "D"])
    )
    assert gamecfg.config_path() == expected


def test_a_running_game_outranks_the_likely_places(tmp_path, monkeypatch):
    old = _install(tmp_path / "old")
    live = _install(tmp_path / "live")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "old",))
    monkeypatch.setattr(gamecfg, "_from_processes", lambda: iter([tmp_path / "live"]))
    assert gamecfg.config_path() == live
    assert gamecfg.config_path() != old


def test_a_directory_without_the_file_does_not_count(tmp_path, monkeypatch):
    (tmp_path / "empty" / "Config").mkdir(parents=True)
    expected = _install(tmp_path / "valid")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "empty", tmp_path / "valid"))
    assert gamecfg.config_path() == expected


def test_read_flag_uses_the_discovered_file(tmp_path, monkeypatch):
    _install(tmp_path / "game")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "game",))
    assert gamecfg.read_flag("EnableChat") is True


def test_missing_values_use_the_given_default():
    assert gamecfg.read_flag("EnableChat", default=True) is True
    assert gamecfg.read_flag("EnableChat") is False


def test_a_moved_install_is_found_again(tmp_path, monkeypatch):
    old = _install(tmp_path / "before")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "before",))
    assert gamecfg.config_path() == old

    old.unlink()
    new = _install(tmp_path / "after")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "after",))
    assert gamecfg.config_path() == new


def test_an_explicit_path_skips_discovery(tmp_path):
    file = tmp_path / "custom.cfg"
    file.write_text("EnableChat=false\n", encoding="utf-8")
    assert gamecfg.read_flag("EnableChat", file, default=True) is False


def test_discovery_does_not_repeat_the_same_folder(tmp_path, monkeypatch):
    directory = tmp_path / "game"
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (directory, directory))
    monkeypatch.setattr(gamecfg, "_from_processes", lambda: iter([directory]))
    monkeypatch.setattr(gamecfg, "_from_drives", lambda: iter([directory]))
    assert list(gamecfg.installation_dirs()) == [directory]


def test_a_broken_process_list_does_not_break_discovery(tmp_path, monkeypatch):
    def explode():
        raise RuntimeError("permission denied")
        yield  # pragma: no cover

    expected = _install(tmp_path / "game")
    monkeypatch.setattr(gamecfg, "_from_processes", explode)
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "game",))
    assert gamecfg.config_path() == expected
