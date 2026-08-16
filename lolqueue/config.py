from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

QUEUES: dict[int, str] = {
    400: "Normal Draft",
    420: "Ranqueada Solo/Duo",
    430: "Normal Blind",
    440: "Ranqueada Flex",
    450: "ARAM",
    490: "Partida Rápida",
    1700: "Arena",
}


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LoLQueue" / "config.json"


@dataclass
class Config:
    auto_accept: bool = True
    auto_queue: bool = False
    auto_pick: bool = False
    auto_ban: bool = False
    queue_id: int = 420
    pick_priority: list[int] = field(default_factory=list)
    ban_priority: list[int] = field(default_factory=list)
    lock_delay_seconds: float = 3.0

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Lê a config do disco. Ausente ou corrompida cai nos padrões."""
        target = path or config_path()
        try:
            # utf-8-sig aceita com e sem BOM: o Notepad do Windows grava
            # com, e um BOM inesperado descartaria tudo em silêncio.
            raw = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
