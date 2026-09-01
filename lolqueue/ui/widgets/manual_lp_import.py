"""Diálogo para recuperar PDL antigo sem automatizar fontes de terceiros.

O usuário vê o delta na fonte que preferir e cola somente o número exato
na linha correspondente. A associação final continua sendo validada contra
o histórico local do cliente antes de qualquer gravação.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.lp_history import ManualLpInput, RANKED_QUEUE_IDS


QUEUE_LABELS = {
    "SOLORANKED": "Ranqueada Solo/Duo",
    "FLEXRANKED": "Ranqueada Flexível",
}


def parse_manual_delta(value: str) -> int | None:
    """Aceita ``+22``, ``-18`` ou ``0`` — nunca um número ambíguo."""

    text = value.strip().replace("−", "-").replace("＋", "+")
    if text == "0":
        return 0
    if not re.fullmatch(r"[+-]\d+", text):
        return None
    return int(text)


class ManualLpImportDialog(QDialog):
    """Tabela curta para o usuário preencher vários N/D de uma vez."""

    def __init__(self, matches, resolve_name=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("manualLpImportDialog")
        self.setWindowTitle("Preencher PDLs")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.resize(640, 510)
        self._rows: tuple[ManualLpInput, ...] = ()
        self._fields: list[tuple[object, QLineEdit]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("RECUPERAR PDL DAS PARTIDAS")
        title.setObjectName("manualLpTitle")
        layout.addWidget(title)
        intro = QLabel(
            "Confira o delta exato em uma fonte de sua confiança e preencha "
            "somente as partidas que deseja recuperar. O aplicativo valida "
            "cada uma no cliente do LoL antes de salvar."
        )
        intro.setObjectName("manualLpIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        hint = QLabel("Use +22 para ganho, -18 para perda ou 0 para uma partida sem alteração.")
        hint.setObjectName("manualLpHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setObjectName("manualLpScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        rows_layout = QVBoxLayout(content)
        rows_layout.setContentsMargins(0, 0, 3, 0)
        rows_layout.setSpacing(7)
        for match in matches:
            queue_id = RANKED_QUEUE_IDS.get(getattr(match, "queue_type", ""))
            game_id = getattr(match, "local_game_id", None)
            if queue_id is None or not isinstance(game_id, int):
                continue
            rows_layout.addWidget(self._row(match, resolve_name))
        rows_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self._error = QLabel()
        self._error.setObjectName("manualLpError")
        self._error.setWordWrap(True)
        self._error.hide()
        layout.addWidget(self._error)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.setObjectName("manualLpCancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = QPushButton("Salvar PDLs")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.accept)
        actions.addWidget(save)
        layout.addLayout(actions)

    def _row(self, match, resolve_name) -> QFrame:
        row = QFrame()
        row.setObjectName("manualLpRow")
        box = QHBoxLayout(row)
        box.setContentsMargins(14, 10, 12, 10)
        box.setSpacing(12)

        words = QVBoxLayout()
        words.setSpacing(2)
        resolved = resolve_name(match.champion_id) if resolve_name else None
        champion = QLabel(resolved or match.champion_name)
        champion.setObjectName("manualLpChampion")
        words.addWidget(champion)
        queue = QUEUE_LABELS.get(match.queue_type, match.queue_type)
        result = "Vitória" if match.result == "WIN" else "Derrota"
        when = match.played_at.astimezone().strftime("%d/%m · %H:%M")
        detail = QLabel(
            f"{result} · {queue} · {match.kills}/{match.deaths}/{match.assists} · {when}"
        )
        detail.setObjectName("manualLpMatchDetail")
        words.addWidget(detail)
        box.addLayout(words, 1)

        field = QLineEdit()
        field.setObjectName("manualLpInput")
        field.setPlaceholderText("+22")
        field.setAccessibleName(f"PDL de {champion.text()}")
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setMaxLength(8)
        field.setFixedWidth(78)
        field.textChanged.connect(self._clear_error)
        box.addWidget(field, 0, Qt.AlignmentFlag.AlignVCenter)
        self._fields.append((match, field))
        return row

    def inputs(self) -> tuple[ManualLpInput, ...]:
        """Entradas validadas depois que o usuário confirma o diálogo."""

        return self._rows

    def _clear_error(self) -> None:
        self._error.hide()

    def accept(self) -> None:  # noqa: D102 (Qt override)
        rows: list[ManualLpInput] = []
        invalid: QLineEdit | None = None
        for match, field in self._fields:
            text = field.text().strip()
            if not text:
                continue
            delta = parse_manual_delta(text)
            if delta is None:
                invalid = field
                break
            queue_id = RANKED_QUEUE_IDS.get(match.queue_type)
            game_id = match.local_game_id
            if queue_id is None or not isinstance(game_id, int):
                # A lista só deveria conter linhas elegíveis. Ainda assim,
                # não aceitamos uma linha caso tenha sido trocada sob nós.
                invalid = field
                break
            rows.append(
                ManualLpInput(
                    game_id=game_id,
                    queue_id=queue_id,
                    champion_id=match.champion_id,
                    ended_at=match.played_at,
                    delta=delta,
                )
            )
        if invalid is not None:
            self._error.setText("Digite +22, -18 ou 0. Todo valor diferente de zero precisa ter sinal.")
            self._error.show()
            invalid.setFocus()
            return
        if not rows:
            self._error.setText("Informe ao menos um PDL ou use Cancelar.")
            self._error.show()
            return
        self._rows = tuple(rows)
        super().accept()
