from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ...resources import background_path
from ..theme import Palette


class Backdrop(QWidget):
    """Moldura da janela com a arte do rift protegida por uma camada escura.

    A pintura fica aqui, e não no QSS, para o caminho funcionar tanto no
    fonte quanto no executável do PyInstaller e para a imagem sempre ocupar
    a janela sem deformar.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self._image = QPixmap(str(background_path()))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bounds = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(bounds, 18, 18)
        painter.setClipPath(path)

        if self._image.isNull():
            painter.fillRect(bounds, QColor(Palette.BACKGROUND))
        else:
            scaled = self._image.scaled(
                bounds.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            source = QRect(
                max(0, (scaled.width() - bounds.width()) // 2),
                max(0, (scaled.height() - bounds.height()) // 2),
                min(bounds.width(), scaled.width()),
                min(bounds.height(), scaled.height()),
            )
            painter.drawPixmap(bounds, scaled, source)

        # Uma camada em dois estágios dá contraste ao texto e ainda deixa a
        # ilustração aparecer nas bordas.
        painter.fillRect(bounds, QColor(3, 10, 22, 172))
        shade = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        shade.setColorAt(0.0, QColor(4, 11, 25, 120))
        shade.setColorAt(0.52, QColor(5, 13, 29, 76))
        shade.setColorAt(1.0, QColor(2, 7, 17, 185))
        painter.fillRect(bounds, shade)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(119, 151, 190, 88), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
