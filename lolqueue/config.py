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


#: Rotas como o cliente as nomeia em `assignedPosition`, na ordem em que
#: aparecem no mapa. É esse campo que revela autofill e rota secundária:
#: seja qual for o motivo, ele diz onde o jogador caiu de verdade.
POSITIONS: tuple[str, ...] = ("top", "jungle", "middle", "bottom", "utility")

POSITION_NAMES: dict[str, str] = {
    "top": "Topo",
    "jungle": "Selva",
    "middle": "Meio",
    "bottom": "Atirador",
    "utility": "Suporte",
}


def position_name(position: str) -> str:
    return POSITION_NAMES.get(position.casefold(), position)


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LoLQueue" / "config.json"


def champion_ids(value) -> list[int]:
    """Filtra uma lista de prioridade, deixando só ids plausíveis.

    Aplicado na leitura e na gravação: um id malformado não casa com
    campeão nenhum, então só ocuparia uma posição da prioridade sem
    nunca ser escolhido. Quem sabe quais ids existem de verdade é o
    catálogo, que poda o resto quando carrega.

    `bool` é subclasse de `int` em Python — daí a checagem explícita,
    senão um `true` no arquivo viraria o campeão de id 1.
    """
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    ]


@dataclass
class Config:
    auto_accept: bool = True
    auto_queue: bool = False
    auto_pick: bool = False
    auto_ban: bool = False
    queue_id: int = 420
    pick_priority: list[int] = field(default_factory=list)
    ban_priority: list[int] = field(default_factory=list)
    pick_priority_by_position: dict[str, list[int]] = field(default_factory=dict)
    lock_delay_seconds: float = 3.0

    def __post_init__(self) -> None:
        self.sanitize()

    def sanitize(self) -> None:
        """Descarta ids malformados das listas de prioridade.

        Roda na construção (cobre a leitura do disco) e de novo antes de
        gravar, porque a UI escreve nos campos direto por `setattr`.
        """
        self.pick_priority = champion_ids(self.pick_priority)
        self.ban_priority = champion_ids(self.ban_priority)
        self.pick_priority_by_position = self._clean_positions()

    def _clean_positions(self) -> dict[str, list[int]]:
        """Só rotas que o cliente conhece, e só com lista de verdade.

        Lista vazia é descartada em vez de guardada: guardá-la faria
        `pick_list` decidir entre vazio e ausente duas vezes, e as duas
        querem dizer a mesma coisa — usar a lista geral.
        """
        source = self.pick_priority_by_position
        if not isinstance(source, dict):
            return {}
        cleaned: dict[str, list[int]] = {}
        for position, value in source.items():
            if not isinstance(position, str):
                continue
            key = position.casefold()
            if key not in POSITIONS:
                continue
            ids = champion_ids(value)
            if ids:
                cleaned[key] = ids
        return cleaned

    def pick_list(self, position: str | None) -> list[int]:
        """Prioridade de escolha para a rota que o cliente atribuiu.

        Cai na lista geral quando a rota não tem lista própria. Isso
        cobre de uma vez o modo cego (que não atribui rota), o autofill
        numa rota que o usuário não configurou e quem prefere uma lista
        só para tudo.
        """
        if position:
            specific = self.pick_priority_by_position.get(position.casefold())
            if specific:
                return specific
        return self.pick_priority

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
        self.sanitize()
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
