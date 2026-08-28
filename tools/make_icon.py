"""Desenha o ícone do app e grava `lolqueue/assets/icon.ico`.

O ícone é o mesmo anel da tela inicial: trilho escuro, arco dourado
aberto e a ponta turquesa que marca a busca em andamento. Desenhar em
vez de guardar um binário opaco deixa a identidade visual num lugar só
— mudar a paleta em `theme.py` e rodar isto de novo basta.

Uso:

    py tools/make_icon.py

O container ICO é montado à mão: é um cabeçalho de 6 bytes, uma entrada
de 16 bytes por tamanho e os PNGs em seguida. Fazer isso aqui evita
trazer o Pillow só para empacotar.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from lolqueue.resources import icon_path  # noqa: E402
from lolqueue.ui.theme import Palette  # noqa: E402

#: Windows escolhe o tamanho conforme o contexto: 16 na barra de
#: título, 32 na barra de tarefas, 256 na visualização grande.
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: Onde o arco começa e quanto varre. Em dezesseis avos de grau, como o
#: Qt pede. A abertura no canto é o que dá movimento ao símbolo.
START_ANGLE = 120 * 16
SWEEP = -300 * 16


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    plate = QRectF(0, 0, size, size)
    radius = size * 0.22

    # Placa de fundo com gradiente radial: mais clara no centro, funda
    # nas quinas. Dá o mesmo ar de vidro/joia dos cards da interface em
    # vez de uma silhueta lisa.
    plate_path = QPainterPath()
    plate_path.addRoundedRect(plate, radius, radius)
    fundo = QRadialGradient(plate.center(), size * 0.72, plate.center())
    fundo.setColorAt(0.0, QColor(Palette.SURFACE_HIGH))
    fundo.setColorAt(0.55, QColor(Palette.BACKGROUND))
    fundo.setColorAt(1.0, QColor(Palette.INK))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fundo)
    painter.drawPath(plate_path)

    # Contorno fino e claro na borda da placa: a lâmina de luz que separa
    # o "vidro" do que está atrás dele.
    if size >= 32:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 28), max(1.0, size * 0.012)))
        painter.drawPath(plate_path)

    thickness = max(1.0, size * 0.105)
    # Nos tamanhos grandes a moldura dá respiro; nos pequenos ela come o
    # símbolo, e na barra de tarefas o anel vira um ponto.
    inset = size * (0.24 if size >= 48 else 0.15)
    ring = QRectF(inset, inset, size - inset * 2, size - inset * 2)

    # Trilho do anel com leve gradiente vertical — dá volume sem pesar.
    trilho = QLinearGradient(ring.topLeft(), ring.bottomRight())
    trilho.setColorAt(0.0, QColor(Palette.SURFACE_HIGH))
    trilho.setColorAt(1.0, QColor(Palette.BORDER))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(trilho, thickness))
    painter.drawEllipse(ring)

    # Halo por trás do arco dourado: um traço mais grosso e translúcido,
    # como um brilho suave, antes do traço nítido por cima.
    if size >= 48:
        glow = QPen(QColor(Palette.ACCENT), thickness * 1.9)
        glow.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_color = QColor(Palette.ACCENT)
        glow_color.setAlpha(70)
        glow.setColor(glow_color)
        painter.setPen(glow)
        painter.drawArc(ring, START_ANGLE, SWEEP)

    arco = QLinearGradient(ring.topLeft(), ring.bottomRight())
    arco.setColorAt(0.0, QColor("#E8D2A0"))
    arco.setColorAt(1.0, QColor(Palette.ACCENT))
    pen = QPen(arco, thickness)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawArc(ring, START_ANGLE, SWEEP)

    # A ponta turquesa some abaixo de 24px: vira um borrão que suja o
    # anel em vez de acrescentar informação.
    if size >= 24:
        tip = QPointF(ring.center().x() + ring.width() / 2, ring.center().y())
        dot_radius = thickness * 0.62

        if size >= 48:
            halo = QRadialGradient(tip, dot_radius * 2.6)
            halo_color = QColor(Palette.ACTIVE)
            halo_color.setAlpha(130)
            halo.setColorAt(0.0, halo_color)
            halo_edge = QColor(Palette.ACTIVE)
            halo_edge.setAlpha(0)
            halo.setColorAt(1.0, halo_edge)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(tip, dot_radius * 2.6, dot_radius * 2.6)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Palette.ACTIVE))
        painter.drawEllipse(tip, dot_radius, dot_radius)

    painter.end()
    return image


def encode_png(image: QImage) -> bytes:
    # O QByteArray precisa de nome: passado direto ao QBuffer, o objeto
    # temporário some no coletor de lixo do Python enquanto o buffer em
    # C++ ainda escreve nele — e o processo cai com violação de acesso.
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def build_ico(frames: list[bytes], sizes: tuple[int, ...]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries, body = b"", b""
    for size, png in zip(sizes, frames):
        # 256 não cabe num byte e é gravado como zero, por convenção do
        # próprio formato.
        side = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset
        )
        offset += len(png)
        body += png
    return header + entries + body


def main() -> int:
    app = QApplication([])  # noqa: F841 — precisa viver até o fim do desenho
    frames = [encode_png(draw(size)) for size in SIZES]
    target = icon_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_ico(frames, SIZES))
    print(f"{target} — {target.stat().st_size} bytes, {len(SIZES)} tamanhos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
