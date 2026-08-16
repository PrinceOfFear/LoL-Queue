from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import psutil

CLIENT_PROCESS = "LeagueClientUx.exe"
LOCKFILE_RE = re.compile(r"^[^:]+:\d+:(\d+):([^:]+):https?$")

CANDIDATE_DIRS = (
    Path(r"C:\Riot Games\League of Legends"),
    Path(r"C:\Program Files\Riot Games\League of Legends"),
    Path(r"D:\Riot Games\League of Legends"),
)


@dataclass(frozen=True)
class Credentials:
    port: int
    token: str

    @property
    def base_url(self) -> str:
        return f"https://127.0.0.1:{self.port}"


def parse_lockfile(content: str) -> Credentials | None:
    match = LOCKFILE_RE.match(content.strip())
    if match is None:
        return None
    return Credentials(port=int(match.group(1)), token=match.group(2))


def _client_process() -> psutil.Process | None:
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] == CLIENT_PROCESS:
            return proc
    return None


def credentials_from_lockfile() -> Credentials | None:
    directories = list(CANDIDATE_DIRS)
    proc = _client_process()
    if proc is not None:
        try:
            directories.insert(0, Path(proc.exe()).parent)
        except (psutil.Error, OSError):
            pass
    for directory in directories:
        try:
            content = (directory / "lockfile").read_text(encoding="utf-8")
        except OSError:
            continue
        creds = parse_lockfile(content)
        if creds is not None:
            return creds
    return None


def credentials_from_process() -> Credentials | None:
    proc = _client_process()
    if proc is None:
        return None
    try:
        argv = proc.cmdline()
    except psutil.Error:
        return None
    port: int | None = None
    token: str | None = None
    for arg in argv:
        if arg.startswith("--app-port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                return None
        elif arg.startswith("--remoting-auth-token="):
            token = arg.split("=", 1)[1]
    if port is None or token is None:
        return None
    return Credentials(port=port, token=token)


def discover() -> Credentials | None:
    """Retorna as credenciais do cliente, ou None se ele não estiver aberto.

    Cliente fechado é estado normal, não erro.
    """
    return credentials_from_lockfile() or credentials_from_process()
