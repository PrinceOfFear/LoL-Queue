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


class AssetStore:
    """Imagens do cliente guardadas pelo caminho de onde vieram.

    O `IconStore` sabe montar a URL de um retrato a partir do id do
    campeão. As runas não funcionam assim: o catálogo já entrega o
    caminho pronto de cada ícone, e eles moram em pastas diferentes por
    árvore. Então aqui a chave é a própria URL.

    Mesmas garantias do outro: grava por temporário, e nada estoura —
    um ícone que não veio vira um quadrado vazio, não um app quebrado.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or (icons_dir() / "perks")

    @property
    def directory(self) -> Path:
        return self._dir

    def path_for(self, url: str) -> Path:
        """Um nome de arquivo estável e único para a URL.

        O caminho inteiro vira o nome, com as barras viradas em
        sublinhado: dois ícones de árvores diferentes podem ter o mesmo
        nome de arquivo na origem, e só a pasta os separa. Guardar o
        caminho todo é o que impede um sobrescrever o outro.
        """
        cleaned = url.strip("/").replace("/lol-game-data/assets/", "")
        flat = cleaned.replace("/", "_").replace("\\", "_").lower()
        return self._dir / (flat or "sem-nome")

    def has(self, url: str) -> bool:
        try:
            return self.path_for(url).stat().st_size > 0
        except OSError:
            return False

    def missing(self, urls: Iterable[str]) -> list[str]:
        return [url for url in urls if url and not self.has(url)]

    def fetch(self, client, url: str) -> bool:
        """Baixa uma imagem. Devolve False se não deu, sem estourar."""
        try:
            data = client.raw(url)
        except LcuError:
            return False
        if not data:
            return False
        target = self.path_for(url)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".part")
            temp.write_bytes(data)
            temp.replace(target)
        except OSError:
            return False
        return True

    def fetch_missing(
        self,
        client,
        urls: Iterable[str],
        should_continue: Callable[[], bool] | None = None,
    ) -> int:
        keep_going = should_continue or (lambda: True)
        downloaded = 0
        for url in self.missing(urls):
            if not keep_going():
                break
            if self.fetch(client, url):
                downloaded += 1
        return downloaded
