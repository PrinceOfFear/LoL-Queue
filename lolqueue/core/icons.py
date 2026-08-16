from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable

from ..lcu import endpoints
from ..lcu.client import LcuError


def icons_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LoLQueue" / "icons"


class IconStore:
    """Retratos dos campeões, em cache no disco.

    O cliente do LoL serve os retratos localmente, mas são ~170 arquivos.
    Baixar uma vez e depois reler do disco evita repetir isso a cada
    abertura do app.

    Nenhum método estoura: um retrato que não veio vira só um quadrado
    sem imagem, nunca um app quebrado.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or icons_dir()

    @property
    def directory(self) -> Path:
        return self._dir

    def url_for(self, champion_id: int) -> str:
        return endpoints.CHAMPION_ICON.format(champion_id=champion_id)

    def path_for(self, champion_id: int) -> Path:
        return self._dir / f"{champion_id}.png"

    def has(self, champion_id: int) -> bool:
        path = self.path_for(champion_id)
        try:
            return path.stat().st_size > 0
        except OSError:
            return False

    def missing(self, ids: Iterable[int]) -> list[int]:
        return [champion_id for champion_id in ids if not self.has(champion_id)]

    def fetch(self, client, champion_id: int) -> bool:
        """Baixa um retrato. Devolve False se não deu, sem estourar."""
        try:
            data = client.raw(self.url_for(champion_id))
        except LcuError:
            return False
        if not data:
            return False
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            # Grava num temporário e só então renomeia: um download
            # interrompido não pode deixar um PNG pela metade no cache,
            # que ficaria quebrado para sempre.
            temp = self.path_for(champion_id).with_suffix(".part")
            temp.write_bytes(data)
            temp.replace(self.path_for(champion_id))
        except OSError:
            return False
        return True

    def fetch_missing(
        self,
        client,
        ids: Iterable[int],
        should_continue: Callable[[], bool] | None = None,
    ) -> int:
        """Baixa o que falta. Devolve quantos vieram.

        `should_continue` deixa quem chamou abortar no meio — fechar a
        janela não pode esperar 170 downloads.
        """
        keep_going = should_continue or (lambda: True)
        downloaded = 0
        for champion_id in self.missing(ids):
            if not keep_going():
                break
            if self.fetch(client, champion_id):
                downloaded += 1
        return downloaded
