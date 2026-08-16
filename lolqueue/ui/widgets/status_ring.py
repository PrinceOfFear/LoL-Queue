from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...core.phases import GameflowPhase
from ..theme import PHASE_COLORS, PHASE_LABELS, Palette

RING_THICKNESS = 6
SWEEP_LENGTH = 90 * 16  # comprimento do arco animado, em 1/16 de grau


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


class StatusRing(QWidget):
    """Anel de estado: cor e rótulo pela fase, cronômetro no centro.

    Gira enquanto a fase é ativa; fica parado quando ociosa.
    """

    ACTIVE_PHASES = {
        GameflowPhase.MATCHMAKING.value,
        GameflowPhase.READY_CHECK.value,
        GameflowPhase.CHAMP_SELECT.value,
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self._phase = GameflowPhase.NONE.value
        self._elapsed = 0.0
        self._connected = False
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(16)

    def set_phase(self, phase_value: str, elapsed_seconds: float = 0.0) -> None:
        self._phase = phase_value
        self._elapsed = elapsed_seconds
        self.update()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.update()

    def _advance(self) -> None:
        if self._phase in self.ACTIVE_PHASES:
            self._angle = (self._angle - 40) % (360 * 16)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height()) - RING_THICKNESS * 2
        rect = QRectF(
            (self.width() - side) / 2,
            (self.height() - side) / 2,
            side,
            side,
        )

        painter.setPen(QPen(QColor(Palette.BORDER), RING_THICKNESS))
        painter.drawEllipse(rect)

        color = QColor(PHASE_COLORS.get(self._phase, Palette.TEXT_MUTED))
        if not self._connected:
            color = QColor(Palette.TEXT_MUTED)
        pen = QPen(color, RING_THICKNESS)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self._phase in self.ACTIVE_PHASES:
            painter.drawArc(rect, self._angle, SWEEP_LENGTH)
        else:
            painter.drawArc(rect, 90 * 16, -360 * 16)

        if not self._connected:
            headline, caption = "DESCONECTADO", "abra o cliente do LoL"
        else:
            headline = format_elapsed(self._elapsed)
            caption = PHASE_LABELS.get(self._phase, "—")

        font = QFont(self.font())
        font.setPointSize(30 if self._connected else 15)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(Palette.TEXT))
        top = QRectF(rect.x(), rect.y() + side * 0.32, side, side * 0.24)
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, headline)

        font.setPointSize(9)
        font.setWeight(QFont.Weight.Normal)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        painter.setFont(font)
        painter.setPen(color)
        bottom = QRectF(rect.x(), rect.y() + side * 0.56, side, side * 0.16)
        painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, caption)
        painter.end()
