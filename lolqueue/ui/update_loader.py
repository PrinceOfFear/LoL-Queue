"""Trabalhadores Qt do atualizador; rede e ZIP nunca rodam na thread da tela."""

from __future__ import annotations

import shutil

from PySide6.QtCore import QThread, Signal

from ..atualizacao import (
    GithubReleaseClient,
    Installation,
    UpdateOffer,
    prepare_update,
)


class UpdateCheckLoader(QThread):
    """Consulta a release oficial e confere o manifesto assinado."""

    ready = Signal(object, object)

    def __init__(self, client: GithubReleaseClient, installation: Installation, parent=None) -> None:
        super().__init__(parent)
        self._client = client
        self._installation = installation

    def run(self) -> None:
        try:
            offer: UpdateOffer | None = self._client.check(self._installation.kind)
            error = None
        except Exception as exc:  # a UI converte em texto seguro para o usuario
            offer, error = None, exc
        self.ready.emit(offer, error)


class UpdateDownloadLoader(QThread):
    """Baixa, confere hash e extrai em staging antes de pedir reinicio."""

    progress = Signal(int, int)
    ready = Signal(object, object)

    def __init__(
        self,
        client: GithubReleaseClient,
        offer: UpdateOffer,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._offer = offer

    def run(self) -> None:
        archive = None
        prepared = None
        try:
            archive = self._client.download(
                self._offer, on_progress=lambda done, total: self.progress.emit(done, total)
            )
            prepared = prepare_update(self._offer, archive)
            # O ZIP ja foi extraido e conferido; manter outra copia grande no
            # cache nao ajuda a troca e ocupa espaco no disco do jogador.
            archive.unlink(missing_ok=True)
            error = None
        except Exception as exc:  # mesma barreira da consulta: nunca derruba a GUI
            if archive is not None:
                archive.unlink(missing_ok=True)
            if prepared is not None:
                shutil.rmtree(prepared.stage_dir, ignore_errors=True)
            prepared, error = None, exc
        self.ready.emit(prepared, error)
