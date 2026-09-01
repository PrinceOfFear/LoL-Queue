"""A versao exibida pelo atualizador precisa ser a mesma do pacote."""

from __future__ import annotations

import tomllib
from pathlib import Path

from lolqueue.version import VERSION


def test_runtime_version_matches_project_metadata():
    root = Path(__file__).resolve().parent.parent
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["version"] == VERSION
