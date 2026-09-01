"""Perfil e últimas partidas do invocador conectado, pelo OP.GG.

Cabeçalho com nick#tag, nível e elo por fila, usando os brasões oficiais
empacotados. O retrato de perfil remoto continua de fora: baixar imagem de
URL arbitrária seria um mecanismo novo só por cosmética. Abaixo, uma linha
por partida reaproveita o cache de retrato de campeão por id, via LCU.

Sem cliente aberto, sem identidade resolvida ou falha do OP.GG: mesmo
aviso de vazio que `AnalysisPage` já usa — um cabeçalho vazio com uma
lista de partidas por baixo pareceria defeito, e não é.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.lp_history import (
    LP_SOURCE_LOCAL_SNAPSHOT,
    LP_SOURCE_MANUAL,
    RANKED_QUEUE_IDS,
    format_lp_delta,
)
from ...core.summoner_history import relative_time
from ..widgets.illustrated_empty import IllustratedEmptyState
from ..widgets.loadout_studio import rank_pixmap

MATCH_PORTRAIT = QSize(40, 40)
LEVEL_BADGE = QSize(16, 16)
RUNE_ICON = QSize(20, 20)
SPELL_ICON = QSize(20, 20)
ITEM_ICON = QSize(24, 24)
# A lista de partidas precisa dar mais peso visual aos itens que o placar
# completo, mas sete ícones em uma única faixa fariam KDA/PDL sumirem nas
# larguras menores. Quatro por linha deixam a build legível e estável.
HISTORY_ITEM_ICON = QSize(30, 30)
HISTORY_ITEM_COLUMNS = 4
HISTORY_ITEMS_WIDTH = (
    HISTORY_ITEM_COLUMNS * HISTORY_ITEM_ICON.width()
    + (HISTORY_ITEM_COLUMNS - 1) * 2
    + 10
)
RANK_ICON = QSize(58, 58)
# O detalhe da partida é o lugar em que a build precisa ser lida, não
# apenas reconhecida por cor. A primeira versão com 24 px ainda deixava os
# itens pequenos ao lado do retrato do campeão. Com 30 px, cada componente
# continua em uma única faixa (como no cliente do LoL), mas fica legível sem
# transformar as dez linhas do placar em cartões altos demais.
SCOREBOARD_ITEM_ICON = QSize(30, 30)
SCOREBOARD_ITEMS_WIDTH = 7 * SCOREBOARD_ITEM_ICON.width() + 6 * 2
# Estes limites absorvem o espaço adicional dos itens na menor largura
# suportada. Nome e dano continuam sendo as duas colunas elásticas.
SCOREBOARD_KDA_WIDTH = 60
SCOREBOARD_ECONOMY_WIDTH = 90
SCOREBOARD_DAMAGE_MIN_WIDTH = 142

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

RANK_TIER_LABELS = {
    "IRON": "Ferro",
    "BRONZE": "Bronze",
    "SILVER": "Prata",
    "GOLD": "Ouro",
    "PLATINUM": "Platina",
    "EMERALD": "Esmeralda",
    "DIAMOND": "Diamante",
    "MASTER": "Mestre",
    "GRANDMASTER": "Grão-Mestre",
    "CHALLENGER": "Desafiante",
}


def _duration_text(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def _damage_text(value: int) -> str:
    """Separador brasileiro sem depender da localidade do Windows."""

    return f"{value:,}".replace(",", ".")


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

    #: O usuário quer informar PDLs já conferidos. A janela abre o diálogo
    #: e a thread que valida a LCU; esta página continua só apresentando UI.
    manual_lp_import_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resolve_icon = None
        self._resolve_name = None
        self._resolve_item_icon = None
        self._resolve_spell_icon = None
        self._resolve_keystone_icon = None
        self._resolve_secondary_style_icon = None
        self._matches = ()
        self._history_loading = False
        self._manual_importing = False
        # O placar aberto guarda o id da partida para receber o PDL caso a
        # notificação do cliente chegue alguns segundos depois dos detalhes.
        self._open_detail = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(1)
        title = QLabel("HISTÓRICO DE PARTIDAS")
        title.setObjectName("pageTitle")
        words.addWidget(title)
        subtitle = QLabel(
            "Partidas, PDL confirmado no cliente, PDL informado e placar completo do invocador conectado."
        )
        subtitle.setObjectName("pageSubtitle")
        # No menor tamanho da janela, o texto explicativo pode ocupar duas
        # linhas; ele não deve obrigar a aba inteira a criar rolagem lateral.
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        words.addWidget(subtitle)
        heading.addLayout(words)
        heading.addStretch(1)
        self._manual_import_button = QPushButton("Preencher PDL")
        self._manual_import_button.setObjectName("historyImportButton")
        self._manual_import_button.setToolTip(
            "Preencha PDLs antigos que você conferiu em uma fonte externa. "
            "Cada linha será validada no cliente do LoL antes de salvar."
        )
        self._manual_import_button.clicked.connect(self._request_manual_import)
        heading.addWidget(
            self._manual_import_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self._refresh_button = QPushButton("Atualizar")
        self._refresh_button.setObjectName("primaryButton")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        # O aviso de vazio e o conteúdo se revezam, igual à análise: um
        # dos dois está sempre escondido, e nunca os dois ao mesmo tempo.
        self._empty = IllustratedEmptyState(
            asset="ranks/all.png",
            mini_assets=(
                "ranks/bronze.png",
                "ranks/gold.png",
                "ranks/diamond.png",
            ),
            eyebrow="HISTÓRICO COMPETITIVO",
            title="Seu desempenho, com contexto",
            detail=(
                "Perfil ranqueado, vitórias, KDA, itens, runas e o placar "
                "completo das partidas aparecem aqui."
            ),
            footnote="Conecte o cliente do LoL e use Atualizar.",
        )
        layout.addWidget(self._empty)

        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        layout.addWidget(self._content)
        self._content.hide()

        # A lista e o placar de uma partida vivem lado a lado dentro do
        # mesmo conteúdo — só um dos dois fica visível por vez, igual ao
        # revezamento entre `_empty` e `_content` logo acima.
        self._list_view = QWidget()
        list_box = QVBoxLayout(self._list_view)
        list_box.setContentsMargins(0, 0, 0, 0)
        list_box.setSpacing(14)
        list_box.addWidget(self._build_hero())
        self._matches_box = QVBoxLayout()
        self._matches_box.setSpacing(8)
        list_box.addLayout(self._matches_box)
        list_box.addStretch(1)
        content.addWidget(self._list_view)

        self._scoreboard_view = self._build_scoreboard()
        content.addWidget(self._scoreboard_view)
        self._scoreboard_view.hide()

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

    def set_loading(self, loading: bool) -> None:
        """Avisa que uma consulta ao OP.GG está em andamento.

        Sem isto, uma resposta demorada (rede lenta, cliente do LoL
        ocupado) e uma travada pareciam a mesma coisa — a tela ficava
        exatamente igual até a consulta terminar. O botão muda de
        rótulo e a lista para de aceitar clique novo enquanto isso.
        """
        self._history_loading = loading
        self._refresh_button.setEnabled(not loading)
        self._refresh_button.setText("Atualizando…" if loading else "Atualizar")
        self._update_manual_import_button()
        self._list_view.setEnabled(not loading)
        self.setCursor(
            Qt.CursorShape.WaitCursor if loading else Qt.CursorShape.ArrowCursor
        )

    def set_history(self, profile, matches) -> None:
        """Mostra perfil e partidas, ou volta ao aviso de vazio.

        `profile` vindo `None` é "sem identidade resolvida ou o OP.GG
        não respondeu" — a página toda some, como na análise.
        """
        self.set_loading(False)
        if profile is None:
            self._matches = ()
            self._update_manual_import_button()
            self._content.hide()
            self._empty.show()
            return

        matches = tuple(matches)
        self._matches = matches
        self._update_manual_import_button()

        self._name.setText(f"{profile.game_name}#{profile.tag_line}")
        self._level.setText(f"Nível {profile.level}")
        self._fill_ranks(profile.ranks)
        self._fill_matches(matches)
        self._refresh_open_detail_lp(matches)

        self._empty.hide()
        self._content.show()

    def manual_lp_matches(self) -> tuple:
        """Linhas em que o jogador pode informar PDL sem vínculo ambíguo."""

        return tuple(
            match
            for match in self._matches
            if (
                match.lp_delta is None
                and match.queue_type in RANKED_QUEUE_IDS
                and isinstance(match.local_game_id, int)
            )
        )

    def set_manual_importing(self, importing: bool) -> None:
        """Mostra que a LCU está conferindo os valores informados."""

        self._manual_importing = importing
        self._update_manual_import_button()

    def _request_manual_import(self) -> None:
        matches = self.manual_lp_matches()
        if matches:
            self.manual_lp_import_requested.emit(matches)

    def _update_manual_import_button(self) -> None:
        eligible = bool(self.manual_lp_matches())
        self._manual_import_button.setEnabled(
            eligible and not self._history_loading and not self._manual_importing
        )
        self._manual_import_button.setText(
            "Validando PDL…" if self._manual_importing else "Preencher PDL"
        )

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
            tier_label = RANK_TIER_LABELS.get(rank.tier.upper(), rank.tier.title())
            value = f"{tier_label} {rank.division} · {rank.lp} PDL"
            self._ranks.addWidget(
                self._rank_measure(rank.tier, label.upper(), value, rate)
            )

    @staticmethod
    def _rank_measure(tier: str, label: str, value: str, rate: str) -> QWidget:
        """Resumo ranqueado com o brasão oficial do elo."""

        block = QFrame()
        block.setObjectName("rankSummary")
        block.setProperty("tier", tier.casefold())
        box = QHBoxLayout(block)
        box.setContentsMargins(10, 7, 13, 7)
        box.setSpacing(10)

        crest = QLabel()
        crest.setObjectName("rankCrestSmall")
        crest.setFixedSize(RANK_ICON)
        crest.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = rank_pixmap(tier, RANK_ICON)
        if not pixmap.isNull():
            crest.setPixmap(pixmap)
        crest.setAccessibleName(f"Brasão {tier.title()}")
        box.addWidget(crest)

        words = QVBoxLayout()
        words.setSpacing(1)
        top = QLabel(label)
        top.setObjectName("cardLabel")
        words.addWidget(top)
        bottom = QLabel(value)
        bottom.setObjectName("rankValue")
        words.addWidget(bottom)
        win_rate = QLabel(f"{rate} de vitórias")
        win_rate.setObjectName("rankRate")
        words.addWidget(win_rate)
        box.addLayout(words)
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
        result_key = "win" if match.result == "WIN" else "lose"
        row.setObjectName("historyMatchRow")
        row.setProperty("result", result_key)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setMinimumHeight(88)
        row.clicked.connect(lambda: self.match_selected.emit(match))
        box = QGridLayout(row)
        box.setContentsMargins(16, 11, 16, 11)
        box.setHorizontalSpacing(12)
        box.setVerticalSpacing(3)
        box.setColumnStretch(2, 1)

        box.addWidget(
            self._portrait_with_level(match.champion_id, match.champion_level), 0, 0, 2, 1
        )

        icons = QHBoxLayout()
        icons.setSpacing(3)
        icons.addLayout(self._spell_icons(match))
        icons.addLayout(self._rune_icons(match))
        box.addLayout(icons, 0, 1, 2, 1)

        name = self._resolve_name(match.champion_id) if self._resolve_name else None
        champion = QLabel(name or match.champion_name)
        champion.setObjectName("historyChampion")
        box.addWidget(champion, 0, 2)
        result = "Vitória" if match.result == "WIN" else "Derrota"
        mode = QUEUE_LABELS.get(match.queue_type, match.queue_type)
        detail = QLabel(f"{result} · {mode}")
        detail.setObjectName("historyMatchSubtitle")
        detail.setProperty("result", result_key)
        box.addWidget(detail, 1, 2)

        box.addWidget(
            self._history_item_icons(match),
            0,
            3,
            2,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )

        kda = QLabel(f"{match.kills}/{match.deaths}/{match.assists}")
        kda.setObjectName("historyKda")
        kda.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        box.addWidget(kda, 0, 4)
        economy = QLabel(f"{match.cs} CS · {_damage_text(match.gold)} ouro")
        economy.setObjectName("historyMatchStat")
        economy.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        box.addWidget(economy, 1, 4)

        direction = "gain" if (match.lp_delta or 0) > 0 else "loss" if (
            match.lp_delta or 0
        ) < 0 else "neutral" if match.lp_delta is not None else "unavailable"
        lp_box = QFrame()
        lp_box.setObjectName("historyLpBox")
        lp_box.setProperty("direction", direction)
        lp_box.setMinimumWidth(78)
        source = getattr(match, "lp_source", "")
        lp_box.setProperty("source", source)
        if match.lp_delta is None:
            tooltip = (
                "O cliente não tinha um registro de PDL para esta partida. "
                "Use Preencher PDL para salvar um valor que você conferiu."
                if match.queue_type in RANKED_QUEUE_IDS
                and isinstance(match.local_game_id, int)
                else "O cliente não tinha um registro de PDL para esta partida."
            )
        elif source == LP_SOURCE_MANUAL:
            tooltip = (
                "PDL informado manualmente por você e validado contra esta "
                "partida local. Um registro oficial do cliente tem prioridade."
            )
        elif source == LP_SOURCE_LOCAL_SNAPSHOT:
            tooltip = (
                "PDL comprovado pela comparação dos retratos do cliente "
                "antes e depois desta partida."
            )
        else:
            tooltip = "PDL confirmado pelo cliente do League of Legends."
        lp_box.setToolTip(tooltip)
        lp_layout = QVBoxLayout(lp_box)
        lp_layout.setContentsMargins(9, 5, 9, 5)
        lp_layout.setSpacing(0)
        lp_caption = QLabel("PDL")
        lp_caption.setObjectName("historyLpCaption")
        if source == LP_SOURCE_MANUAL:
            lp_caption.setText("PDL · INFORMADO")
        lp_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_layout.addWidget(lp_caption)
        lp = QLabel(
            format_lp_delta(match.lp_delta)
            if match.lp_delta is not None
            else "N/D"
        )
        lp.setObjectName("lpDelta")
        lp.setProperty("direction", direction)
        lp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_layout.addWidget(lp)
        box.addWidget(lp_box, 0, 5, 2, 1)

        time_box = QFrame()
        time_box.setObjectName("historyTimeBox")
        time_box.setMinimumWidth(62)
        time_layout = QVBoxLayout(time_box)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(1)
        duration = QLabel(_duration_text(match.duration_seconds))
        duration.setObjectName("historyDuration")
        duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        time_layout.addWidget(duration)
        when = QLabel(relative_time(match.played_at, now))
        when.setObjectName("historyWhen")
        when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        time_layout.addWidget(when)
        box.addWidget(time_box, 0, 6, 2, 1)
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

    def _item_icons(self, match, size: QSize = ITEM_ICON) -> QHBoxLayout:
        """A grade de itens, do tamanho que a partida realmente comprou."""
        box = QHBoxLayout()
        box.setSpacing(2)
        names = getattr(match, "item_names", ())
        for index, item_id in enumerate(match.items):
            icon = self._icon_label(
                "itemIcon", size, self._resolve_item_icon, item_id
            )
            name = names[index] if index < len(names) else ""
            if isinstance(name, str) and name:
                # O nome aparece ao pausar sobre o ícone e também ajuda
                # leitores de tela; é uma segunda forma de ler a build sem
                # depender de ampliar ainda mais toda a linha do placar.
                icon.setToolTip(name)
                icon.setAccessibleName(f"Item: {name}")
            box.addWidget(icon)
        return box

    def _history_item_icons(self, match) -> QFrame:
        """Build maior em duas linhas, sem alargar a linha do histórico.

        O placar completo usa uma faixa horizontal propositalmente menor,
        pois precisa comportar cinco jogadores por equipe. Na lista, a build
        é um dos principais sinais para reconhecer a partida; reservamos
        quatro colunas e deixamos a segunda linha receber o trinket.
        """

        holder = QFrame()
        holder.setObjectName("historyItems")
        holder.setFixedWidth(HISTORY_ITEMS_WIDTH)
        grid = QGridLayout(holder)
        grid.setContentsMargins(5, 5, 5, 5)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        grid.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for index, item_id in enumerate(match.items):
            icon = self._icon_label(
                "itemIcon", HISTORY_ITEM_ICON, self._resolve_item_icon, item_id
            )
            line, column = divmod(index, HISTORY_ITEM_COLUMNS)
            grid.addWidget(icon, line, column)
        return holder

    # -- Placar completo de uma partida -----------------------------------
    #
    # `MatchSummary` (a linha da lista) e `ParticipantDetail` (a linha do
    # placar) compartilham os mesmos nomes de campo — champion_id, items,
    # spells, primary_rune_id, secondary_style_id, champion_level — de
    # propósito, então `_portrait_with_level`, `_rune_icons`, `_spell_icons`
    # e `_item_icons` acima servem para os dois sem duplicar nada.

    def _build_scoreboard(self) -> QWidget:
        view = QWidget()
        box = QVBoxLayout(view)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(14)

        header = QHBoxLayout()
        self._back_button = QPushButton("← Voltar")
        self._back_button.setObjectName("primaryButton")
        self._back_button.clicked.connect(self._show_list)
        header.addWidget(self._back_button)

        words = QVBoxLayout()
        words.setSpacing(1)
        self._scoreboard_title = QLabel()
        self._scoreboard_title.setObjectName("heroHeadline")
        words.addWidget(self._scoreboard_title)
        self._scoreboard_subtitle = QLabel()
        self._scoreboard_subtitle.setObjectName("heroDetail")
        words.addWidget(self._scoreboard_subtitle)
        header.addLayout(words)
        header.addStretch(1)
        box.addLayout(header)

        self._teams_box = QVBoxLayout()
        self._teams_box.setSpacing(14)
        box.addLayout(self._teams_box)
        box.addStretch(1)
        return view

    def _show_list(self) -> None:
        self._open_detail = None
        self._scoreboard_view.hide()
        self._list_view.show()

    def set_game_detail(self, detail) -> None:
        """Desenha o placar completo, ou volta para a lista.

        `detail` vindo `None` é "a busca do placar falhou" — a página
        fica (ou volta) na lista, em vez de mostrar uma tela quebrada.
        """
        self.set_loading(False)
        if detail is None:
            self._show_list()
            return

        self._open_detail = detail
        self._set_scoreboard_header(detail)
        self._fill_teams(detail.teams)

        self._list_view.hide()
        self._scoreboard_view.show()

    def _set_scoreboard_header(self, detail) -> None:
        """Atualiza o cabeçalho sem reconstruir as dez linhas do placar."""

        target_team = next(
            (
                team
                for team in detail.teams
                if any(participant.is_target for participant in team.participants)
            ),
            None,
        )
        result = "Vitória" if target_team is not None and target_team.win else "Derrota"
        mode = QUEUE_LABELS.get(detail.queue_type, detail.queue_type)
        when = detail.played_at.astimezone().strftime("%d/%m/%Y %H:%M")
        self._scoreboard_title.setText(result)
        subtitle = f"{mode} · {_duration_text(detail.duration_seconds)} · {when}"
        if detail.lp_delta is not None:
            subtitle = f"{subtitle} · {format_lp_delta(detail.lp_delta)}"
            if detail.lp_source == LP_SOURCE_MANUAL:
                subtitle = f"{subtitle} · informado"
        self._scoreboard_subtitle.setText(subtitle)

    def _refresh_open_detail_lp(self, matches) -> None:
        """Inclui o PDL que chegou depois, sem tirar o usuário do placar."""

        detail = self._open_detail
        if detail is None:
            return
        for match in matches:
            if match.match_id != detail.match_id or match.lp_delta is None:
                continue
            if (
                match.lp_delta != detail.lp_delta
                or match.lp_source != detail.lp_source
            ):
                self._open_detail = replace(
                    detail,
                    lp_delta=match.lp_delta,
                    lp_source=match.lp_source,
                )
                self._set_scoreboard_header(self._open_detail)
            return

    def _fill_teams(self, teams) -> None:
        while self._teams_box.count():
            item = self._teams_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        max_damage = max(
            (participant.damage_to_champions for team in teams for participant in team.participants),
            default=1,
        )
        for team in teams:
            self._teams_box.addWidget(self._team_block(team, max_damage))

    def _team_block(self, team, max_damage: int) -> QFrame:
        """Uma equipe com cabeçalho compacto e a mesma grade em todas as linhas."""

        block = QFrame()
        team_key = team.key.casefold()
        block.setObjectName("scoreboardTeamCard")
        block.setProperty("team", team_key)
        box = QVBoxLayout(block)
        box.setContentsMargins(16, 13, 16, 14)
        box.setSpacing(7)

        heading = QHBoxLayout()
        side = QLabel("EQUIPE AZUL" if team.key == "BLUE" else "EQUIPE VERMELHA")
        side.setObjectName("scoreboardTeamName")
        side.setProperty("team", team_key)
        heading.addWidget(side)
        result = QLabel("VITÓRIA" if team.win else "DERROTA")
        result.setObjectName("scoreboardTeamResult")
        result.setProperty("result", "win" if team.win else "lose")
        heading.addWidget(result)
        heading.addStretch(1)
        box.addLayout(heading)

        objectives = QLabel(
            f"{team.kills} abates  ·  {team.towers} torres  ·  {team.dragons} dragões  ·  "
            f"{team.barons} barões  ·  {team.heralds} arautos  ·  {_damage_text(team.gold)} ouro"
        )
        objectives.setObjectName("scoreboardObjectives")
        objectives.setWordWrap(True)
        box.addWidget(objectives)

        if team.banned_champion_names:
            bans = QLabel("Banidos: " + ", ".join(team.banned_champion_names))
            bans.setObjectName("scoreboardBans")
            bans.setWordWrap(True)
            box.addWidget(bans)

        box.addWidget(self._scoreboard_column_header())
        for participant in team.participants:
            box.addWidget(self._participant_row(participant, max_damage))
        return block

    @staticmethod
    def _configure_scoreboard_columns(grid: QGridLayout) -> None:
        """A mesma grade no cabeçalho e nas cinco linhas de cada equipe."""

        # Uma separação ligeiramente menor preserva o alinhamento de todas
        # as colunas depois de ampliar os sete itens da build.
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(0)
        grid.setColumnMinimumWidth(0, MATCH_PORTRAIT.width())
        grid.setColumnMinimumWidth(1, SPELL_ICON.width() * 2 + 3)
        grid.setColumnMinimumWidth(2, 94)
        grid.setColumnMinimumWidth(3, SCOREBOARD_ITEMS_WIDTH)
        grid.setColumnMinimumWidth(4, SCOREBOARD_KDA_WIDTH)
        grid.setColumnMinimumWidth(5, SCOREBOARD_ECONOMY_WIDTH)
        grid.setColumnMinimumWidth(6, SCOREBOARD_DAMAGE_MIN_WIDTH)
        # Nome e dano ganham a largura livre sem deslocar as outras colunas.
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(6, 1)

    def _scoreboard_column_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("scoreboardColumns")
        grid = QGridLayout(header)
        grid.setContentsMargins(12, 2, 12, 2)
        self._configure_scoreboard_columns(grid)

        player = QLabel("JOGADOR")
        player.setObjectName("scoreboardColumnLabel")
        player.setMinimumWidth(0)
        player.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        player.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(player, 0, 0, 1, 3)
        for column, text in (
            (3, "ITENS"),
            (4, "KDA"),
            (5, "CS / OURO"),
            (6, "DANO A CAMPEÕES"),
        ):
            label = QLabel(text)
            label.setObjectName("scoreboardColumnLabel")
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(label, 0, column)
        return header

    def _participant_row(self, participant, max_damage: int) -> QFrame:
        """Uma linha de placar com métricas sempre na mesma coluna.

        Antes, cada grupo era acrescentado livremente a um ``QHBoxLayout``.
        Bastava um nome maior ou sete itens para empurrar KDA e dano de lugar.
        A grade abaixo é compartilhada com o cabeçalho da equipe, portanto a
        leitura continua estável nas dez linhas da partida.
        """

        row = QFrame()
        row.setObjectName("optionCard")
        row.setProperty("target", "true" if participant.is_target else "false")
        row.setProperty("team", participant.team_key.lower())
        row.setMinimumHeight(66)
        grid = QGridLayout(row)
        grid.setContentsMargins(12, 8, 12, 8)
        self._configure_scoreboard_columns(grid)

        grid.addWidget(self._participant_identity(participant), 0, 0, 1, 3)
        grid.addWidget(self._scoreboard_items(participant), 0, 3)
        grid.addWidget(
            self._scoreboard_metric(
                f"{participant.kills}/{participant.deaths}/{participant.assists}",
                SCOREBOARD_KDA_WIDTH,
                "kda",
            ),
            0,
            4,
        )
        grid.addWidget(
            self._scoreboard_metric(
                f"{participant.cs} · {_damage_text(participant.gold)}",
                SCOREBOARD_ECONOMY_WIDTH,
                "economy",
            ),
            0,
            5,
        )
        grid.addWidget(self._damage_metric(participant, max_damage), 0, 6)
        return row

    def _participant_identity(self, participant) -> QWidget:
        """Retrato, feitiços e nome em uma única célula do placar."""

        identity = QWidget()
        identity.setObjectName("scoreboardIdentity")
        box = QHBoxLayout(identity)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(
            self._portrait_with_level(participant.champion_id, participant.champion_level)
        )

        icons = QHBoxLayout()
        icons.setContentsMargins(0, 0, 0, 0)
        icons.setSpacing(3)
        icons.addLayout(self._spell_icons(participant))
        icons.addLayout(self._rune_icons(participant))
        box.addLayout(icons)

        naming = QVBoxLayout()
        naming.setContentsMargins(0, 0, 0, 0)
        naming.setSpacing(1)
        name = (
            self._resolve_name(participant.champion_id) if self._resolve_name else None
        )
        champion = QLabel(name or participant.champion_name)
        champion.setObjectName("scoreboardChampion")
        champion.setToolTip(champion.text())
        champion.setMinimumWidth(0)
        champion.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        name_line = QHBoxLayout()
        name_line.setContentsMargins(0, 0, 0, 0)
        name_line.setSpacing(5)
        # O próprio nome recebe o espaço flexível. Um ``addStretch`` depois
        # dele faria uma QLabel com política Ignored encolher até zero.
        name_line.addWidget(champion, 1)
        if participant.is_target:
            you = QLabel("VOCÊ")
            you.setObjectName("youBadge")
            name_line.addWidget(you, 0, Qt.AlignmentFlag.AlignVCenter)
        naming.addLayout(name_line)

        summoner = QLabel(f"{participant.game_name}#{participant.tag_line}")
        summoner.setObjectName("scoreboardSummoner")
        summoner.setToolTip(summoner.text())
        summoner.setMinimumWidth(0)
        summoner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        naming.addWidget(summoner)
        box.addLayout(naming, 1)
        return identity

    def _scoreboard_items(self, participant) -> QWidget:
        """Sete itens legíveis, em uma faixa que não move as demais colunas."""

        holder = QWidget()
        holder.setObjectName("scoreboardItems")
        holder.setFixedWidth(SCOREBOARD_ITEMS_WIDTH)
        items = self._item_icons(participant, SCOREBOARD_ITEM_ICON)
        items.setContentsMargins(0, 0, 0, 0)
        items.addStretch(1)
        holder.setLayout(items)
        return holder

    @staticmethod
    def _scoreboard_metric(value: str, width: int, metric: str) -> QFrame:
        tile = QFrame()
        tile.setObjectName("scoreboardMetric")
        tile.setProperty("metric", metric)
        tile.setFixedWidth(width)
        box = QVBoxLayout(tile)
        box.setContentsMargins(4, 4, 4, 4)
        box.setSpacing(0)

        number = QLabel(value)
        number.setObjectName("scoreboardMetricValue")
        number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(number)
        return tile

    @staticmethod
    def _damage_metric(participant, max_damage: int) -> QFrame:
        damage = QFrame()
        damage.setObjectName("scoreboardDamage")
        damage.setMinimumWidth(SCOREBOARD_DAMAGE_MIN_WIDTH)
        damage.setToolTip("Dano total causado a campeões nesta partida.")
        box = QVBoxLayout(damage)
        box.setContentsMargins(8, 3, 8, 3)
        box.setSpacing(2)

        value = QLabel(_damage_text(participant.damage_to_champions))
        value.setObjectName("damageValue")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        box.addWidget(value)

        meter = QProgressBar()
        meter.setObjectName("damageBar")
        meter.setProperty("team", participant.team_key.casefold())
        meter.setRange(0, max(1, max_damage))
        meter.setValue(participant.damage_to_champions)
        meter.setTextVisible(False)
        meter.setFixedHeight(7)
        meter.setAccessibleName(
            f"{_damage_text(participant.damage_to_champions)} de dano a campeões"
        )
        box.addWidget(meter)
        return damage
