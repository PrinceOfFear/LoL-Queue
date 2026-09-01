from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

#: Altura da barra. A janela usa isto para saber onde o arrasto começa.
TITLEBAR_HEIGHT = 46


class TitleBar(QWidget):
    """Barra própria: a janela não tem moldura nativa.

    A moldura do Windows some de propósito para o app manter a identidade
    visual, então os controles que normalmente viveriam nela precisam estar
    aqui também. O estado do botão central é atualizado pela janela quando
    ela alterna entre maximizada e restaurada.
    """

    def __init__(
        self,
        minimize,
        maximize,
        close,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("titlebar")
        self.setFixedHeight(TITLEBAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 0, 12, 0)
        title = QLabel("CENTRAL DE FILA")
        title.setObjectName("windowTitle")
        layout.addWidget(title)
        layout.addStretch(1)
        mode = QLabel("AUTOMAÇÃO")
        mode.setObjectName("topPill")
        layout.addWidget(mode)
        layout.addSpacing(10)
        self._maximize_button = QPushButton()
        self._maximize_button.setObjectName("maximizeButton")
        self._maximize_button.clicked.connect(maximize)

        for text, name, slot in (("−", "windowButton", minimize),):
            button = QPushButton(text)
            button.setObjectName(name)
            button.clicked.connect(slot)
            layout.addWidget(button)
        layout.addWidget(self._maximize_button)

        close_button = QPushButton("×")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(close)
        layout.addWidget(close_button)
        self.set_maximized(False)

    def set_maximized(self, maximized: bool) -> None:
        """Mostra a ação que o clique vai executar, não o estado atual."""

        self._maximize_button.setText("❐" if maximized else "□")
        self._maximize_button.setToolTip(
            "Restaurar tamanho da janela" if maximized else "Maximizar janela"
        )
