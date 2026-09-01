"""Estado vazio ilustrado, compartilhado pelas páginas de dados tardios."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...resources import asset_path

MAIN_ART = QSize(126, 126)
MINI_ART = QSize(28, 28)


def _asset_pixmap(relative: str, size: QSize) -> QPixmap:
    source = QPixmap(str(asset_path(relative)))
    if source.isNull():
        return source
    # Os mapas do cliente guardam o estado ativo e o inativo empilhados.
    if relative.startswith("maps/") and source.height() > source.width():
        source = source.copy(0, 0, source.width(), source.width())
    return source.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class IllustratedEmptyState(QFrame):
    """Cartão explicativo que evita uma página grande parecer quebrada."""

    def __init__(
        self,
        *,
        asset: str,
        mini_assets: tuple[str, ...],
        eyebrow: str,
        title: str,
        detail: str,
        footnote: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(330)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(48, 34, 48, 34)
        layout.setSpacing(42)
        layout.addStretch(1)

        art = QFrame()
        art.setObjectName("emptyArt")
        art.setFixedSize(188, 196)
        art_box = QVBoxLayout(art)
        art_box.setContentsMargins(20, 17, 20, 14)
        art_box.setSpacing(8)
        main = QLabel()
        main.setObjectName("emptyMainImage")
        main.setFixedSize(MAIN_ART)
        main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = _asset_pixmap(asset, MAIN_ART)
        if not pixmap.isNull():
            main.setPixmap(pixmap)
        art_box.addWidget(main, 0, Qt.AlignmentFlag.AlignHCenter)

        minis = QHBoxLayout()
        minis.setSpacing(7)
        minis.addStretch(1)
        for relative in mini_assets:
            icon = QLabel()
            icon.setObjectName("emptyMiniIcon")
            icon.setFixedSize(34, 34)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mini = _asset_pixmap(relative, MINI_ART)
            if not mini.isNull():
                icon.setPixmap(mini)
            minis.addWidget(icon)
        minis.addStretch(1)
        art_box.addLayout(minis)
        layout.addWidget(art, 0, Qt.AlignmentFlag.AlignVCenter)

        words = QVBoxLayout()
        words.setSpacing(8)
        words.addStretch(1)
        self.eyebrow_label = QLabel(eyebrow)
        self.eyebrow_label.setObjectName("emptyEyebrow")
        words.addWidget(self.eyebrow_label)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("emptyTitle")
        words.addWidget(self.title_label)
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("emptyDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setMaximumWidth(440)
        words.addWidget(self.detail_label)
        self.footnote_label = QLabel(footnote)
        self.footnote_label.setObjectName("emptyFootnote")
        self.footnote_label.setWordWrap(True)
        self.footnote_label.setMaximumWidth(440)
        words.addWidget(self.footnote_label)
        words.addStretch(1)
        layout.addLayout(words, 1)
        layout.addStretch(1)

    def set_copy(
        self,
        *,
        eyebrow: str | None = None,
        title: str | None = None,
        detail: str | None = None,
        footnote: str | None = None,
    ) -> None:
        """Troca o texto do estado sem reconstruir a ilustração.

        A mesma arte pode explicar estados bem diferentes: cliente fechado,
        automação pausada e uma consulta externa indisponível.  Refazer
        o cartão para cada um deixa widgets antigos no layout e torna a
        transição visivelmente instável.
        """
        if eyebrow is not None:
            self.eyebrow_label.setText(eyebrow)
        if title is not None:
            self.title_label.setText(title)
        if detail is not None:
            self.detail_label.setText(detail)
        if footnote is not None:
            self.footnote_label.setText(footnote)


__all__ = ["IllustratedEmptyState"]
