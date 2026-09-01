from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import (
    FLASH_KEYS,
    OPGG_TIERS,
    POSITION_QUEUES,
    Config,
    preference_name,
)
from ...resources import asset_path
from ..binding import ConfigBinder
from ..widgets.log_pane import LogPane
from ..widgets.loadout_studio import rank_icon
from ..widgets.pick_order import PickOrderPanel
from ..widgets.rune_tree import RuneTreeView
from ..widgets.status_ring import StatusRing

PREDICTION_ICON = QSize(38, 38)
#: Casa com a largura do chip de previsão; mais que isso rouba espaço
#: do texto do cartão, e menos corta os nomes longos de campeão.
ORDER_WIDTH = 236

FEATURE_ICON_SIZE = QSize(28, 28)

POSITION_ASSETS: dict[str, str] = {
    "": "unselected.png",
    "top": "top.png",
    "jungle": "jungle.png",
    "middle": "middle.png",
    "bottom": "bottom.png",
    "utility": "utility.png",
    "fill": "fill.png",
}

FEATURE_CONFIG_FIELDS = frozenset(
    {
        "queue_id",
        "primary_position",
        "secondary_position",
        "flash_key",
        "auto_spells",
        "opgg_tier",
        "auto_runes",
        "auto_items",
    }
)


def _rune_option_text(key: str) -> str:
    """Rótulo curto para uma página de elo ou de confronto."""
    if key.startswith("vs "):
        confronto = key[3:]
        if " — " in confronto:
            opponent, criterion = confronto.split(" — ", 1)
            return f"vs {opponent} · {criterion}"
        return f"vs {confronto}"
    return OPGG_TIERS.get(key, key)


class _FeatureTile(QFrame):
    """Cartão pequeno cujo ícone e texto acompanham a conta ativa."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("featureTile")
        self.icon_keys: tuple[str, ...] = ()

        box = QHBoxLayout(self)
        box.setContentsMargins(10, 8, 12, 8)
        box.setSpacing(9)

        icon_group = QWidget()
        icon_layout = QHBoxLayout(icon_group)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(4)
        self.icon_labels: list[QLabel] = []
        for _ in range(2):
            image = QLabel()
            image.setObjectName("featureIcon")
            image.setFixedSize(34, 34)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_layout.addWidget(image)
            self.icon_labels.append(image)
        box.addWidget(icon_group)

        words = QVBoxLayout()
        words.setSpacing(0)
        self.eyebrow_label = QLabel()
        self.eyebrow_label.setObjectName("featureEyebrow")
        words.addWidget(self.eyebrow_label)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("featureDetail")
        words.addWidget(self.detail_label)
        box.addLayout(words, 1)

    def set_content(
        self,
        icons: list[tuple[str, str, QIcon]],
        eyebrow: str,
        detail: str,
        tooltip: str,
    ) -> None:
        """Troca o resumo inteiro e elimina qualquer segundo ícone antigo."""

        self.icon_keys = tuple(key for key, _name, _icon in icons)
        for index, label in enumerate(self.icon_labels):
            if index >= len(icons):
                label.clear()
                label.setAccessibleName("")
                label.setToolTip("")
                label.hide()
                continue
            _key, name, icon = icons[index]
            pixmap = icon.pixmap(FEATURE_ICON_SIZE)
            if pixmap.isNull():
                label.clear()
            else:
                label.setPixmap(pixmap)
            label.setAccessibleName(f"Ícone de {name}")
            label.setToolTip(name)
            label.show()

        self.eyebrow_label.setText(eyebrow)
        self.detail_label.setText(detail)
        self.setAccessibleName(f"{eyebrow}: {detail}")
        self.setToolTip(tooltip)


class DashboardPage(QWidget):
    """Centro visual do app: estado do cliente, comando e histórico."""

    #: O usuário pediu para inverter o motor. Quem decide o que isso
    #: significa é a janela, que é quem fala com o watcher.
    toggled = Signal()

    #: O usuário escolheu a build de runa de outro elo, pela chave do
    #: OP.GG. Quem entrega o pedido ao motor é a janela: esta página não
    #: conhece o cliente do LoL e não é a thread que fala com ele.
    rune_option_chosen = Signal(str)

    #: A ordem de escolha foi reordenada aqui na Central. Quem sabe em
    #: qual lista isso vai parar — a geral ou a da rota da partida — é a
    #: janela, que é quem acompanha a seleção.
    pick_order_changed = Signal(list)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        binder: ConfigBinder | None = None,
    ) -> None:
        super().__init__(parent)
        self._binder = binder
        self._feature_config = binder.config if binder is not None else Config()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(13)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        wording = QVBoxLayout()
        wording.setSpacing(1)
        title = QLabel("CENTRAL DE FILA")
        title.setObjectName("pageTitle")
        wording.addWidget(title)
        subtitle = QLabel("Controle sua sessão sem perder o foco da partida.")
        subtitle.setObjectName("pageSubtitle")
        wording.addWidget(subtitle)
        header.addLayout(wording)
        header.addStretch(1)
        shortcut = QLabel("F5  iniciar   ·   F6  parar")
        shortcut.setObjectName("hotkeyChip")
        header.addWidget(shortcut, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(30, 18, 30, 18)
        hero_layout.setSpacing(30)

        ring_column = QVBoxLayout()
        ring_column.setContentsMargins(0, 0, 0, 0)
        self.ring = StatusRing()
        ring_column.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        ring_label = QLabel("SINAL DO CLIENTE")
        ring_label.setObjectName("cardLabel")
        ring_column.addWidget(ring_label, 0, Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addLayout(ring_column, 0)

        details = QVBoxLayout()
        details.setContentsMargins(0, 4, 0, 4)
        details.setSpacing(8)
        eyebrow = QLabel("PRONTO QUANDO VOCÊ ESTIVER")
        eyebrow.setObjectName("heroEyebrow")
        details.addWidget(eyebrow)
        self._headline = QLabel("Sua central de partida")
        self._headline.setObjectName("heroHeadline")
        details.addWidget(self._headline)
        self._detail = QLabel(
            "Abra o cliente do League of Legends e deixe o LoL Queue cuidar "
            "da fila, das confirmações e das suas prioridades."
        )
        self._detail.setObjectName("heroDetail")
        self._detail.setWordWrap(True)
        details.addWidget(self._detail)
        details.addSpacing(5)

        self._button = QPushButton("INICIAR AUTOMAÇÃO")
        self._button.setObjectName("primaryButton")
        self._button.setProperty("running", "false")
        self._button.clicked.connect(self.toggled)
        details.addWidget(self._button, 0, Qt.AlignmentFlag.AlignLeft)

        # Prévia de quem a lista de prioridade vai travar assim que a
        # partida abrir. Só aparece durante a seleção — nasce escondida
        # porque fora dela não há previsão nenhuma para mostrar.
        #
        # Mora na coluna do anel, e não embaixo do botão, por duas razões
        # que apontam para o mesmo lado: a coluna do anel tem folga de
        # altura de sobra e a do texto não tinha nenhuma; e ali ela lê
        # como continuação do estado da partida — o que está
        # acontecendo, seguido de quem vai ser travado.
        self._prediction = QFrame()
        self._prediction.setObjectName("predictionChip")
        prediction_layout = QHBoxLayout(self._prediction)
        prediction_layout.setContentsMargins(12, 8, 16, 8)
        prediction_layout.setSpacing(12)
        self._prediction_icon = QLabel()
        self._prediction_icon.setFixedSize(PREDICTION_ICON)
        self._prediction_icon.setScaledContents(True)
        prediction_layout.addWidget(self._prediction_icon)
        prediction_wording = QVBoxLayout()
        prediction_wording.setSpacing(0)
        prediction_eyebrow = QLabel("PRÓXIMA ESCOLHA")
        prediction_eyebrow.setObjectName("predictionEyebrow")
        prediction_wording.addWidget(prediction_eyebrow)
        self._prediction_name = QLabel()
        self._prediction_name.setObjectName("predictionName")
        prediction_wording.addWidget(self._prediction_name)
        prediction_layout.addLayout(prediction_wording)
        prediction_layout.addStretch(1)
        ring_column.addSpacing(12)
        ring_column.addWidget(self._prediction, 0, Qt.AlignmentFlag.AlignHCenter)
        ring_column.addStretch(1)
        self._prediction.hide()

        # A ordem de prioridade, editável aqui mesmo — sem trocar de
        # página no meio da seleção, com o relógio correndo. Fica ao lado
        # do cartão de runas, e não embaixo da prévia, por altura: na
        # coluna do anel ela empurrava o registro para fora da janela no
        # tamanho mínimo; aqui divide a altura que a grade de runas já
        # pedia.
        self._order = PickOrderPanel()
        self._order.setFixedWidth(ORDER_WIDTH)
        self._order.reordered.connect(self.pick_order_changed)

        # As builds de runa que o OP.GG devolveu para os elos de
        # comparação. Nasce escondido: fora da seleção, e sem opção que
        # tenha chegado de verdade, não há o que oferecer.
        self._runes = QFrame()
        self._runes.setObjectName("optionCard")
        runes_layout = QVBoxLayout(self._runes)
        runes_layout.setContentsMargins(12, 9, 12, 11)
        runes_layout.setSpacing(7)
        # Título e seletor na mesma linha. Empilhados, o cartão passava da
        # altura que a janela no tamanho mínimo tem para dar, e o painel de
        # registro era empurrado para fora da tela.
        runes_header = QHBoxLayout()
        runes_header.setContentsMargins(0, 0, 0, 0)
        runes_header.setSpacing(10)
        runes_eyebrow = QLabel("RUNAS POR ELO / CONFRONTO")
        runes_eyebrow.setObjectName("predictionEyebrow")
        runes_header.addWidget(runes_eyebrow, 0, Qt.AlignmentFlag.AlignVCenter)
        self._rune_options = QHBoxLayout()
        self._rune_options.setContentsMargins(0, 0, 0, 0)
        self._rune_options.setSpacing(8)
        runes_header.addLayout(self._rune_options)
        runes_header.addStretch(1)
        runes_layout.addLayout(runes_header)
        # A página desenhada como no jogo, logo abaixo do seletor de elo.
        # Mostra sempre a que está no cliente; trocar de elo troca as duas
        # coisas ao mesmo tempo, então o que se vê é o que está aplicado.
        self._rune_tree = RuneTreeView()
        runes_layout.addWidget(self._rune_tree)
        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(12)
        options_row.addWidget(self._runes, 0, Qt.AlignmentFlag.AlignTop)
        options_row.addWidget(self._order, 0, Qt.AlignmentFlag.AlignTop)
        options_row.addStretch(1)
        details.addLayout(options_row)
        self._runes.hide()

        # Um resumo vivo da conta ocupa o respiro do herói quando não há
        # seleção em andamento. Ele não anuncia recursos genéricos: mostra
        # exatamente as rotas, a tecla do Flash e o elo configurados agora.
        self._features = QWidget()
        feature_row = QHBoxLayout(self._features)
        feature_row.setContentsMargins(0, 0, 0, 0)
        feature_row.setSpacing(8)
        self._route_feature = _FeatureTile()
        self._flash_feature = _FeatureTile()
        self._build_feature = _FeatureTile()
        feature_row.addWidget(self._route_feature, 1)
        feature_row.addWidget(self._flash_feature, 1)
        feature_row.addWidget(self._build_feature, 1)
        details.addWidget(self._features)
        self._refresh_features()
        if binder is not None:
            binder.changed.connect(self._on_feature_config_changed)
            binder.on_reload(self._refresh_features)

        # Preenchidos quando o catálogo de runas termina de carregar e a
        # cada publicação do motor. Sem catálogo a grade fica de fora e
        # os botões de elo continuam funcionando sozinhos.
        self._perks = None
        self._resolve_icon = None
        self._builds: dict = {}
        self._active_tier: str | None = None

        details.addStretch(1)

        note = QLabel("A automação só atua no cliente conectado.")
        note.setObjectName("hint")
        details.addWidget(note)
        hero_layout.addLayout(details, 1)
        layout.addWidget(hero, 1)

        log_card = QFrame()
        log_card.setObjectName("logCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(18, 10, 18, 12)
        self._log = LogPane()
        log_layout.addWidget(self._log)
        layout.addWidget(log_card)

    @staticmethod
    def _position_icon(position: str) -> QIcon:
        filename = POSITION_ASSETS.get(position, POSITION_ASSETS[""])
        return QIcon(str(asset_path(f"positions/{filename}")))

    def _refresh_features(self) -> None:
        """Redesenha os três cartões a partir do perfil que está valendo."""

        config = self._feature_config

        if config.queue_id not in POSITION_QUEUES:
            route_icons = [
                ("unselected", "fila sem escolha de rota", self._position_icon(""))
            ]
            route_detail = "Esta fila não usa rotas"
            route_tooltip = "A fila selecionada não permite escolher rotas."
        elif not config.primary_position:
            route_icons = [
                ("unselected", "rotas atuais do cliente", self._position_icon(""))
            ]
            route_detail = "Como está no cliente"
            route_tooltip = "O app preservará as rotas que já estiverem no cliente."
        else:
            positions = [config.primary_position]
            if config.secondary_position:
                positions.append(config.secondary_position)
            route_icons = [
                (position, preference_name(position), self._position_icon(position))
                for position in positions
            ]
            route_detail = (
                "Qualquer rota"
                if positions == ["fill"]
                else " + ".join(preference_name(position) for position in positions)
            )
            route_tooltip = f"Rotas escolhidas: {route_detail}."
        self._route_feature.set_content(
            route_icons,
            "ROTAS",
            route_detail,
            route_tooltip,
        )

        flash_key = str(config.flash_key).casefold()
        flash_detail = FLASH_KEYS.get(flash_key, "Como já estiver na conta")
        spell_state = "ligada" if config.auto_spells else "desligada"
        self._flash_feature.set_content(
            [
                (
                    "flash",
                    "Flash",
                    QIcon(str(asset_path("spells/flash.png"))),
                )
            ],
            "FLASH",
            flash_detail,
            f"Tecla configurada do Flash. Aplicação automática {spell_state}.",
        )

        tier = str(config.opgg_tier).casefold()
        build_detail = OPGG_TIERS.get(tier, tier)
        build_state = (
            "ativa"
            if config.auto_runes or config.auto_items
            else "desligada"
        )
        self._build_feature.set_content(
            [(tier, build_detail, rank_icon(tier, QSize(30, 30)))],
            "BUILD",
            build_detail,
            f"Elo usado para buscar a build. Aplicação automática {build_state}.",
        )

    def _on_feature_config_changed(self, attribute: str) -> None:
        if attribute in FEATURE_CONFIG_FIELDS:
            self._refresh_features()

    def set_running(self, running: bool) -> None:
        self._button.setProperty("running", "true" if running else "false")
        self._button.setText("PAUSAR AUTOMAÇÃO" if running else "INICIAR AUTOMAÇÃO")
        self._headline.setText("Automação ativa" if running else "Sua central de partida")
        self._detail.setText(
            "A fila e suas escolhas configuradas serão acompanhadas assim que o "
            "cliente estiver disponível."
            if running
            else "Abra o cliente do League of Legends e deixe o LoL Queue cuidar "
            "da fila, das confirmações e das suas prioridades."
        )
        # Propriedade dinâmica só muda a cor depois de repintar.
        self._button.style().unpolish(self._button)
        self._button.style().polish(self._button)

    def set_predicted_pick(self, name: str | None, icon_path: str | None) -> None:
        """Mostra o boneco que a lista travaria agora, ou some se `name` é `None`.

        `icon_path` pode faltar mesmo com `name` preenchido — o retrato
        ainda pode não ter terminado de baixar; o nome sozinho já avisa.
        """
        if name is None:
            self._prediction.hide()
            return
        if icon_path:
            self._prediction_icon.setPixmap(QIcon(icon_path).pixmap(PREDICTION_ICON))
        else:
            self._prediction_icon.setPixmap(QIcon().pixmap(PREDICTION_ICON))
        self._prediction_name.setText(name)
        self._prediction.show()

    def set_pick_resolvers(self, name_of, icon_of) -> None:
        """Entrega ao painel de ordem quem traduz id em nome e retrato."""
        self._order.set_resolvers(name_of, icon_of)

    def set_pick_order(self, ids, scope: str) -> None:
        """Mostra a lista de prioridade que está valendo agora.

        `scope` é o rótulo do que está à vista — a geral ou a da rota —
        porque reordenar a lista errada é um erro silencioso: some com o
        campeão do topo e nada muda na partida.
        """
        self._order.set_scope(scope)
        self._order.set_order(ids)

    def set_rune_catalog(self, catalog, resolve) -> None:
        """Entrega o catálogo que traduz ids de runa em nome e ícone.

        Chega tarde de propósito: é carregado junto com os retratos, numa
        thread à parte. Enquanto não chega, o seletor de elo já funciona
        — só a grade é que não tem como ser desenhada.
        """
        self._perks = catalog
        self._resolve_icon = resolve
        self._draw_tree()

    def set_rune_options(self, tiers, active, builds=None) -> None:
        """Oferece uma build de runa por elo que respondeu de verdade.

        Só chega aqui o que o OP.GG devolveu: lista vazia esconde o
        painel inteiro, em vez de deixar botão sem build atrás. O elo
        que já está no cliente aparece marcado e não é clicável — pedir
        de novo o que já está aplicado só renderia uma linha no registro.

        `builds` traz as runas de cada elo, que é o que permite desenhar
        a árvore embaixo dos botões.
        """
        while self._rune_options.count():
            widget = self._rune_options.takeAt(0).widget()
            if widget is not None:
                # Sair do layout não tira da tela: sem soltar o pai, um
                # botão de uma seleção com mais elos ficaria desenhado
                # por trás dos novos até o Qt apagá-lo.
                widget.setParent(None)
                widget.deleteLater()
        self._builds = dict(builds or {})
        self._active_tier = active
        if not tiers:
            self._draw_tree()
            self._runes.hide()
            self._features.show()
            return
        for tier in tiers:
            atual = tier == active
            build = self._builds.get(tier)
            rune_pages = getattr(build, "rune_pages", ()) if build is not None else ()
            matchup_page = rune_pages[0] if rune_pages else None
            text = _rune_option_text(tier)
            if (
                tier.startswith("vs ")
                and " — " not in tier
                and matchup_page is not None
                and matchup_page.label
            ):
                text = f"{text} · {matchup_page.label}"
            button = QPushButton(text)
            button.setObjectName("runeOption")
            crest = rank_icon(tier, QSize(24, 24))
            if not crest.isNull():
                button.setIcon(crest)
                button.setIconSize(QSize(24, 24))
            # A dica virou balão: como linha de texto ela custava altura
            # que a janela pequena não tem, e o botão desligado já diz
            # sozinho qual elo está no cliente.
            hint = "Troca a página de runas aplicada no cliente."
            if matchup_page is not None and matchup_page.games:
                hint = (
                    f"{round(matchup_page.win_rate * 100)}% de vitórias em "
                    f"{matchup_page.games} partidas contra este campeão. "
                    "Clique para aplicar."
                )
            button.setToolTip(hint)
            button.setProperty("active", "true" if atual else "false")
            button.setEnabled(not atual)
            button.clicked.connect(partial(self.rune_option_chosen.emit, tier))
            self._rune_options.addWidget(button)
        self._draw_tree()
        self._features.hide()
        self._runes.show()

    def _draw_tree(self) -> None:
        """Redesenha a grade do elo que está aplicado no cliente.

        Sem elo ativo — quando as runas vieram da reserva da Riot, que
        não é uma das opções — cai na primeira que respondeu, só para
        não deixar o painel oco. Qual está de fato no cliente continua
        dito pelo botão marcado, que é a fonte de verdade disso.
        """
        if self._perks is None or self._resolve_icon is None:
            return
        build = self._builds.get(self._active_tier)
        if build is None:
            build = next(iter(self._builds.values()), None)
        if build is None:
            self._rune_tree.set_tree(None, self._resolve_icon)
            return
        self._rune_tree.set_tree(
            self._perks.tree(build.style, build.sub_style, build.perks),
            self._resolve_icon,
        )

    def set_log_folder(self, folder) -> None:
        self._log.set_folder(folder)

    def append(self, message: str) -> None:
        self._log.append(message)
