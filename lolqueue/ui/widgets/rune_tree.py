"""A página de runas desenhada como a tela do jogo a mostra.

Nove ids soltos não dizem nada a quem olha. Aqui eles viram a mesma
grade que o jogador vê no cliente: a árvore primária à esquerda, com a
runa-chave em cima; a secundária ao lado, sem chave (o jogo não deixa
levar a de outra árvore) e com uma das três fileiras em branco, porque
lá só se escolhem duas; e os fragmentos numa terceira coluna.

Os fragmentos ficam ao lado, e não embaixo da secundária como no editor
do jogo, por uma razão de espaço medida, não de gosto: empilhados eles
faziam a página inteira pedir 706 px de altura, e a janela no tamanho
mínimo só oferece 604 — o painel de registro era empurrado para fora da
tela. De lado, a grade cabe e nenhuma informação se perde.

O que foi escolhido aparece inteiro e emoldurado; o resto fica apagado
no lugar, para dar a leitura de "esta linha tinha estas opções e a
escolhida foi aquela" — que é justamente a informação que uma lista de
nomes não passa.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

#: Tamanhos por papel. A chave é maior porque é maior no jogo — é o que
#: faz a grade ser reconhecida de relance.
KEYSTONE_SIZE = QSize(32, 32)
RUNE_SIZE = QSize(24, 24)
SHARD_SIZE = QSize(17, 17)
STYLE_SIZE = QSize(18, 18)

#: Quanto sobra de uma runa que não foi escolhida. Baixo o bastante para
#: a escolhida saltar, alto o bastante para ainda se ver o que era.
FADED = 0.26


def _faded(pixmap: QPixmap, opacity: float) -> QPixmap:
    """Uma cópia translúcida do ícone.

    Pintar a transparência no próprio pixmap sai mais barato que dar um
    efeito gráfico a cada ícone: a grade tem umas quarenta casas, e
    efeito por widget nessa quantidade pesa na hora de abrir.
    """
    if pixmap.isNull():
        return pixmap
    faded = QPixmap(pixmap.size())
    faded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faded)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return faded


class RuneTreeView(QWidget):
    """Desenha uma `Tree` do catálogo de runas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resolve = lambda url: None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(22)
        self._primary = QVBoxLayout()
        self._primary.setSpacing(5)
        self._secondary = QVBoxLayout()
        self._secondary.setSpacing(5)
        self._shards = QVBoxLayout()
        self._shards.setSpacing(5)
        layout.addLayout(self._primary)
        layout.addLayout(self._secondary)
        layout.addLayout(self._shards)
        layout.addStretch(1)

    def set_tree(self, tree, resolve=None) -> None:
        """Redesenha a grade. `tree` em `None` esvazia o painel.

        `resolve` traduz o caminho de imagem do catálogo no arquivo já
        baixado. Sem ele — ou com um ícone que ainda não chegou — a casa
        aparece vazia, mas continua no lugar: a forma da árvore não
        depende de as imagens terem vindo.
        """
        if resolve is not None:
            self._resolve = resolve
        self._clear(self._primary)
        self._clear(self._secondary)
        self._clear(self._shards)
        if tree is None:
            return

        self._primary.addWidget(self._heading(tree.primary))
        for index, row in enumerate(tree.primary_rows):
            size = KEYSTONE_SIZE if index == 0 else RUNE_SIZE
            self._primary.addWidget(self._row(row, size))
        self._primary.addStretch(1)

        self._secondary.addWidget(self._heading(tree.secondary))
        for row in tree.secondary_rows:
            self._secondary.addWidget(self._row(row, RUNE_SIZE))
        self._secondary.addStretch(1)

        if tree.shard_rows:
            shards = QLabel("FRAGMENTOS")
            shards.setObjectName("runeTreeLabel")
            self._shards.addWidget(shards)
            for row in tree.shard_rows:
                self._shards.addWidget(self._row(row, SHARD_SIZE))
            self._shards.addStretch(1)

    # ---------- as peças ----------

    def _heading(self, style) -> QWidget:
        """Ícone e nome de uma árvore."""
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 2)
        line.setSpacing(6)
        icon = QLabel()
        icon.setFixedSize(STYLE_SIZE)
        icon.setScaledContents(True)
        pixmap = self._pixmap(style.icon, STYLE_SIZE)
        if pixmap is not None:
            icon.setPixmap(pixmap)
        line.addWidget(icon)
        name = QLabel(style.name.upper())
        name.setObjectName("runeTreeLabel")
        line.addWidget(name)
        line.addStretch(1)
        return holder

    def _row(self, row, size: QSize) -> QWidget:
        """Uma fileira inteira, com altura própria.

        Um widget, e não um layout solto: a grade é redesenhada a cada
        troca de elo, e widget se limpa com `deleteLater()`, que o Qt
        sabe agendar. Layout aninhado teria de ser desmontado à mão, peça
        por peça, a cada redesenho.
        """
        holder = QWidget()
        holder.setFixedHeight(size.height() + 8)
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        for perk in row.perks:
            line.addWidget(self._slot(perk, size, perk.id == row.chosen))
        line.addStretch(1)
        return holder

    def _slot(self, perk, size: QSize, chosen: bool) -> QWidget:
        """Uma casa da grade: a runa, acesa ou apagada."""
        holder = QFrame()
        holder.setObjectName("runeSlot")
        holder.setProperty("chosen", "true" if chosen else "false")
        holder.setFixedSize(size.width() + 8, size.height() + 8)
        box = QHBoxLayout(holder)
        box.setContentsMargins(4, 4, 4, 4)
        icon = QLabel()
        icon.setFixedSize(size)
        icon.setScaledContents(True)
        pixmap = self._pixmap(perk.icon, size)
        if pixmap is not None:
            icon.setPixmap(pixmap if chosen else _faded(pixmap, FADED))
        box.addWidget(icon)
        tip = perk.name if not perk.description else f"{perk.name}\n{perk.description}"
        holder.setToolTip(tip)
        return holder

    def _pixmap(self, url: str, size: QSize) -> QPixmap | None:
        if not url:
            return None
        path = self._resolve(url)
        if not path:
            return None
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        return pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    @staticmethod
    def _clear(layout) -> None:
        """Esvazia uma coluna antes de redesenhá-la.

        Tudo que entra na coluna é widget ou espaçamento, então basta
        tirar item por item. O `setParent(None)` antes do `deleteLater()`
        não é zelo à toa: sair do layout não tira o widget da tela, só
        deixa de posicioná-lo. Sem soltar o pai, a fileira antiga ficava
        desenhada onde estava até o Qt resolver apagá-la — e a grade nova
        aparecia por cima da velha durante a troca de elo.
        """
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
