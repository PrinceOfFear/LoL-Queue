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

from ...config import OPGG_TIERS
from ..widgets.log_pane import LogPane
from ..widgets.pick_order import PickOrderPanel
from ..widgets.rune_tree import RuneTreeView
from ..widgets.status_ring import StatusRing

PREDICTION_ICON = QSize(38, 38)
#: Casa com a largura do chip de previsão; mais que isso rouba espaço
#: do texto do cartão, e menos corta os nomes longos de campeão.
ORDER_WIDTH = 236


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        runes_eyebrow = QLabel("RUNAS POR ELO")
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
            return
        for tier in tiers:
            atual = tier == active
            button = QPushButton(OPGG_TIERS.get(tier, tier))
            button.setObjectName("runeOption")
            # A dica virou balão: como linha de texto ela custava altura
            # que a janela pequena não tem, e o botão desligado já diz
            # sozinho qual elo está no cliente.
            button.setToolTip("Troca a página de runas aplicada no cliente.")
            button.setProperty("active", "true" if atual else "false")
            button.setEnabled(not atual)
            button.clicked.connect(partial(self.rune_option_chosen.emit, tier))
            self._rune_options.addWidget(button)
        self._draw_tree()
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
