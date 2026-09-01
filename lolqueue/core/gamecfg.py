"""Localiza e le flags simples do ``game.cfg`` do League of Legends.

Este leitor e compartilhado por recursos que precisam respeitar uma
configuracao ja escolhida pelo jogador. Ele nao depende de captura de tela
nem de analise do minimapa.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


CONFIG_SUBPATH = Path("Config") / "game.cfg"
INSTALL_SUBPATH = Path("Riot Games") / "League of Legends"
CANDIDATE_DIRS = (
    Path(r"C:\Riot Games\League of Legends"),
    Path(r"C:\Program Files\Riot Games\League of Legends"),
    Path(r"C:\Program Files (x86)\Riot Games\League of Legends"),
)
GAME_PROCESSES = {
    "LeagueClientUx.exe": 1,
    "LeagueClient.exe": 1,
    "League of Legends.exe": 2,
}

_found: Path | None = None


def _from_processes() -> Iterator[Path]:
    """Yield installation directories reported by running League processes."""
    try:
        import psutil
    except Exception:
        return
    try:
        processes = list(psutil.process_iter(["name"]))
    except Exception:
        return
    for process in processes:
        try:
            levels = GAME_PROCESSES.get(process.info.get("name") or "")
        except Exception:
            continue
        if levels is None:
            continue
        try:
            root = Path(process.exe())
        except Exception:
            continue
        for _ in range(levels):
            root = root.parent
        yield root


def _from_drives() -> Iterator[Path]:
    """Yield the usual Riot folder from each locally available drive."""
    try:
        drives = os.listdrives()
    except (AttributeError, OSError):  # pragma: no cover - non-Windows
        return
    for drive in drives:
        yield Path(drive) / INSTALL_SUBPATH


def _collect(source) -> list[Path]:
    try:
        return list(source())
    except Exception:
        return []


def installation_dirs() -> Iterator[Path]:
    """Yield candidate installation directories, strongest evidence first."""
    seen: set[str] = set()
    candidates = [*_collect(_from_processes), *CANDIDATE_DIRS, *_collect(_from_drives)]
    for directory in candidates:
        key = str(directory).casefold()
        if key in seen:
            continue
        seen.add(key)
        yield directory


def config_path(refresh: bool = False) -> Path | None:
    """Return the discovered ``game.cfg``, or ``None`` when it is absent."""
    global _found
    if refresh:
        _found = None
    if _found is not None:
        try:
            if _found.is_file():
                return _found
        except OSError:
            pass
        _found = None
    for directory in installation_dirs():
        candidate = directory / CONFIG_SUBPATH
        try:
            if candidate.is_file():
                _found = candidate
                return candidate
        except OSError:
            continue
    return None


def _read_text(path: Path | None) -> str | None:
    file = path or config_path()
    if file is None:
        return None
    try:
        return file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _value_of(name: str, text: str) -> str | None:
    target = name.casefold()
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip().casefold() == target:
            return value.strip()
    return None


def read_flag(name: str, path: Path | None = None, default: bool = False) -> bool:
    """Read a boolean-like ``game.cfg`` setting without inventing a value."""
    text = _read_text(path)
    if text is None:
        return default
    value = _value_of(name, text)
    if value is None:
        return default
    return value.casefold() not in {"0", "", "false"}
