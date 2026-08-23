"""Perfil e últimas partidas do invocador conectado, pelo OP.GG.

Cabeçalho com nick#tag, nível e elo por fila — só texto: o único ícone
remoto seria o retrato de perfil do OP.GG, e baixar imagem de URL
arbitrária seria um mecanismo novo para um ganho cosmético (a única
imagem que o app já sabe buscar e cachear é o retrato de campeão, por
id, via LCU). Abaixo, uma linha por partida, reaproveitando esse mesmo
cache de retrato.

Sem cliente aberto, sem identidade resolvida ou falha do OP.GG: mesmo
aviso de vazio que `AnalysisPage` já usa — um cabeçalho vazio com uma
lista de partidas por baixo pareceria defeito, e não é.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.summoner_history import relative_time

MATCH_PORTRAIT = QSize(40, 40)
LEVEL_BADGE = QSize(16, 16)
RUNE_ICON = QSize(16, 16)
SPELL_ICON = QSize(16, 16)
ITEM_ICON = QSize(20, 20)

#: Como o OP.GG chama a fila, e como se diz aqui.
QUEUE_LABELS = {
    "SOLORANKED": "Ranqueada Solo/Duo",
    "FLEXRANKED": "Ranqueada Flexível",
    "ARAM": "ARAM",
    "NORMAL": "Normal",
    "ARENA": "Arena",
}

#: Só estas duas filas têm elo que faz sentido estampar no cabeçalho.
RANK_QUEUE_LABELS = {
    "SOLORANKED": "Solo/Duo",
    "FLEXRANKED": "Flexível",
}


def _duration_text(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


class _ClickableFrame(QFrame):
    """Um `QFrame` que também sabe ser clicado — a linha do histórico.

    O `QPushButton` de sempre não serve aqui: a linha inteira precisa
    ser a área de clique, com o próprio layout de KDA/itens/runas por
    cima — um botão desenharia sobre isso ou exigiria repassar cada
    clique de filho manualmente.
    """

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class HistoryPage(QWidget):
    """Perfil e últimas partidas, puxados do OP.GG sob pedido."""

    #: A tela pede uma consulta nova. Quem busca é a janela — esta
    #: página não fala com a rede.
    refresh_requested = Signal()

    #: A partida que o usuário clicou na lista, para a janela buscar o
    #: placar completo dela.
    match_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resolve_icon = None
        self._resolve_name = None
        self._resolve_item_icon = None
        self._resolve_spell_icon = None
        self._resolve_keystone_icon = None
        self._resolve_secondary_style_icon = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(1)
        title = QLabel("HISTÓRICO DE PARTIDAS")
        title.setObjectName("pageTitle")
        words.addWidget(title)
        subtitle = QLabel("As últimas partidas do invocador conectado, pelo OP.GG.")
        subtitle.setObjectName("pageSubtitle")
        words.addWidget(subtitle)
        heading.addLayout(words)
        heading.addStretch(1)
        self._refresh_button = QPushButton("Atualizar")
        self._refresh_button.setObjectName("primaryButton")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        # O aviso de vazio e o conteúdo se revezam, igual à análise: um
        # dos dois está sempre escondido, e nunca os dois ao mesmo tempo.
        self._empty = QLabel(
            "Nada por enquanto. Abra o cliente do LoL para ver perfil e "
            "partidas recentes."
        )
        self._empty.setObjectName("listNotice")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        layout.addWidget(self._content)
        self._content.hide()

        content.addWidget(self._build_hero())
        self._matches_box = QVBoxLayout()
        self._matches_box.setSpacing(8)
        content.addLayout(self._matches_box)
        content.addStretch(1)

    def _build_hero(self) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(24, 16, 24, 16)
        row.setSpacing(18)

        naming = QVBoxLayout()
        naming.setSpacing(2)
        self._name = QLabel()
        self._name.setObjectName("heroHeadline")
        naming.addWidget(self._name)
        self._level = QLabel()
        self._level.setObjectName("heroDetail")
        naming.addWidget(self._level)
        row.addLayout(naming)
        row.addStretch(1)

        self._ranks = QHBoxLayout()
        self._ranks.setSpacing(22)
        row.addLayout(self._ranks)
        return card

    def set_icon_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de campeão em caminho de retrato.

        Chega tarde, junto com os retratos: enquanto não chega, as
        partidas aparecem só com o nome, que já basta para ler.
        """
        self._resolve_icon = resolve

    def set_name_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de campeão em nome português.

        O OP.GG manda o nome em inglês; enquanto o catálogo de
        campeões não carregou, a linha usa o nome que veio junto.
        """
        self._resolve_name = resolve

    def set_item_icon_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de item em caminho de ícone."""
        self._resolve_item_icon = resolve

    def set_spell_icon_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de feitiço de invocador em ícone."""
        self._resolve_spell_icon = resolve

    def set_keystone_icon_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de runa-chave em ícone."""
        self._resolve_keystone_icon = resolve

    def set_secondary_style_icon_resolver(self, resolve) -> None:
        """Entrega o tradutor de id de árvore secundária em ícone."""
        self._resolve_secondary_style_icon = resolve

    def set_history(self, profile, matches) -> None:
        """Mostra perfil e partidas, ou volta ao aviso de vazio.

        `profile` vindo `None` é "sem identidade resolvida ou o OP.GG
        não respondeu" — a página toda some, como na análise.
        """
        if profile is None:
            self._content.hide()
            self._empty.show()
            return

        self._name.setText(f"{profile.game_name}#{profile.tag_line}")
        self._level.setText(f"Nível {profile.level}")
        self._fill_ranks(profile.ranks)
        self._fill_matches(matches)

        self._empty.hide()
        self._content.show()

    def _fill_ranks(self, ranks) -> None:
        while self._ranks.count():
            item = self._ranks.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for rank in ranks:
            label = RANK_QUEUE_LABELS.get(rank.queue_type)
            if label is None or rank.tier is None:
                continue
            games = rank.wins + rank.losses
            rate = f"{rank.wins / games:.0%}" if games else "—"
            value = f"{rank.tier.title()} {rank.division} · {rank.lp} PDL"
            self._ranks.addWidget(self._measure(label.upper(), f"{value}  ({rate})"))

    @staticmethod
    def _measure(label: str, value: str) -> QWidget:
        block = QWidget()
        box = QVBoxLayout(block)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        top = QLabel(label)
        top.setObjectName("cardLabel")
        box.addWidget(top, 0, Qt.AlignmentFlag.AlignHCenter)
        bottom = QLabel(value)
        bottom.setObjectName("cardValue")
        box.addWidget(bottom, 0, Qt.AlignmentFlag.AlignHCenter)
        return block

    def _fill_matches(self, matches) -> None:
        while self._matches_box.count():
            item = self._matches_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        now = datetime.now(timezone.utc)
        for match in matches:
            self._matches_box.addWidget(self._match_row(match, now))

    def _match_row(self, match, now) -> QFrame:
        row = _ClickableFrame()
        row.setObjectName("optionCard")
        row.setProperty("result", "win" if match.result == "WIN" else "lose")
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.clicked.connect(lambda: self.match_selected.emit(match))
        box = QHBoxLayout(row)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(12)

        box.addWidget(self._portrait_with_level(match.champion_id, match.champion_level))

        icons = QHBoxLayout()
        icons.setSpacing(3)
        icons.addLayout(self._spell_icons(match))
        icons.addLayout(self._rune_icons(match))
        box.addLayout(icons)

        naming = QVBoxLayout()
        naming.setSpacing(1)
        name = self._resolve_name(match.champion_id) if self._resolve_name else None
        champion = QLabel(name or match.champion_name)
        champion.setObjectName("predictionName")
        naming.addWidget(champion)
        result = "Vitória" if match.result == "WIN" else "Derrota"
        mode = QUEUE_LABELS.get(match.queue_type, match.queue_type)
        detail = QLabel(f"{result} · {mode}")
        detail.setObjectName("heroDetail")
        naming.addWidget(detail)
        box.addLayout(naming)

        box.addLayout(self._item_icons(match))
        box.addStretch(1)

        kda = QLabel(f"{match.kills}/{match.deaths}/{match.assists}")
        kda.setObjectName("cardValue")
        box.addWidget(kda)

        cs = QLabel(f"{match.cs} CS")
        cs.setObjectName("heroDetail")
        box.addWidget(cs)

        gold = QLabel(f"{match.gold} ouro")
        gold.setObjectName("heroDetail")
        box.addWidget(gold)

        duration = QLabel(_duration_text(match.duration_seconds))
        duration.setObjectName("heroDetail")
        box.addWidget(duration)

        when = QLabel(relative_time(match.played_at, now))
        when.setObjectName("hint")
        box.addWidget(when)
        return row

    def _icon_label(self, object_name: str, size: QSize, resolve, key) -> QLabel:
        label = QLabel()
        label.setObjectName(object_name)
        label.setFixedSize(size)
        label.setScaledContents(True)
        path = resolve(key) if resolve else None
        icon = QIcon(path) if path else QIcon()
        label.setPixmap(icon.pixmap(size))
        return label

    def _portrait_with_level(self, champion_id: int, level: int) -> QWidget:
        """Retrato do campeão com o selo de nível sobreposto no canto.

        As duas peças ocupam a mesma célula de grade — é o jeito mais
        simples de empilhar sem posicionamento manual em pixel.
        """
        holder = QWidget()
        holder.setFixedSize(MATCH_PORTRAIT)
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(
            self._icon_label("", MATCH_PORTRAIT, self._resolve_icon, champion_id), 0, 0
        )
        badge = QLabel(str(level))
        badge.setObjectName("levelBadge")
        badge.setFixedSize(LEVEL_BADGE)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(
            badge, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        return holder

    def _rune_icons(self, match) -> QVBoxLayout:
        """A runa-chave e a árvore secundária, uma sobre a outra."""
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(
            self._icon_label(
                "runeIcon", RUNE_ICON, self._resolve_keystone_icon, match.primary_rune_id
            )
        )
        box.addWidget(
            self._icon_label(
                "runeIcon",
                RUNE_ICON,
                self._resolve_secondary_style_icon,
                match.secondary_style_id,
            )
        )
        return box

    def _spell_icons(self, match) -> QVBoxLayout:
        """Os dois feitiços de invocador, um sobre o outro."""
        box = QVBoxLayout()
        box.setSpacing(2)
        for spell_id in match.spells:
            box.addWidget(
                self._icon_label(
                    "spellIcon", SPELL_ICON, self._resolve_spell_icon, spell_id
                )
            )
        return box

    def _item_icons(self, match) -> QHBoxLayout:
        """A grade de itens, do tamanho que a partida realmente comprou."""
        box = QHBoxLayout()
        box.setSpacing(2)
        for item_id in match.items:
            box.addWidget(
                self._icon_label(
                    "itemIcon", ITEM_ICON, self._resolve_item_icon, item_id
                )
            )
        return box
