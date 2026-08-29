from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...config import PREFERENCE_POSITIONS, QUEUES, preference_name
from ...resources import asset_path
from ..binding import ConfigBinder


#: Marca da fila que a Riot desligou. Fica na lista de propósito: uma
#: opção que some é lida como defeito do app, e o jogador procura o que
#: não vai achar.
UNAVAILABLE_SUFFIX = "  ·  indisponível agora"

#: Rótulo da opção vazia na primeira rota. "Nenhuma" soaria como
#: recusar rota; o que acontece de verdade é o app não tocar no
#: assunto e valer o que o jogador já deixou marcado no cliente.
NO_PRIMARY = "Deixar como está no cliente"

NO_SECONDARY = "Sem segunda rota"


#: Os arquivos da Riot têm bastante respiro transparente. Em 24 px o
#: símbolo continua legível sem fazer a caixa crescer além dos outros
#: controles da página.
POSITION_ICON_SIZE = QSize(24, 24)

#: Cada PNG de mapa traz dois estados de 128 px empilhados. O primeiro é
#: o colorido, usado neste resumo; 72 px preserva os traços sem transformar
#: a escolha da fila num segundo cartão principal.
MAP_ICON_SIZE = QSize(72, 72)

POSITION_ICONS: dict[str, str] = {
    "": "unselected.png",
    "top": "top.png",
    "jungle": "jungle.png",
    "middle": "middle.png",
    "bottom": "bottom.png",
    "utility": "utility.png",
    "fill": "fill.png",
}

#: Arte, nome do mapa e explicação curta para cada fila. As cinco filas
#: abaixo dividem o Rift; ARAM e Arena recebem sua própria leitura visual.
QUEUE_VISUALS: dict[int, tuple[str, str, str]] = {
    400: ("summoners-rift.png", "Summoner's Rift", "Mapa clássico 5v5"),
    420: ("summoners-rift.png", "Summoner's Rift", "Mapa clássico 5v5"),
    430: ("summoners-rift.png", "Summoner's Rift", "Mapa clássico 5v5"),
    440: ("summoners-rift.png", "Summoner's Rift", "Mapa clássico 5v5"),
    490: ("summoners-rift.png", "Summoner's Rift", "Mapa clássico 5v5"),
    450: ("howling-abyss.png", "Howling Abyss", "ARAM · uma única rota"),
    1700: ("rotating-mode.png", "Modo rotativo", "Arena"),
}


class QueuePage(QWidget):
    """Qual fila jogar e se o app volta para ela sozinho."""

    def __init__(self, binder: ConfigBinder, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder = binder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 28)
        layout.setSpacing(16)

        title = QLabel("FILA")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Defina onde a automação deve procurar a próxima partida.")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("contentCard")
        content = QVBoxLayout(card)
        content.setContentsMargins(24, 22, 24, 22)
        content.setSpacing(13)
        label = QLabel("MODO DE PARTIDA")
        label.setObjectName("sectionTitle")
        content.addWidget(label)

        self._summary = QFrame()
        self._summary.setObjectName("queueVisualSummary")
        summary_layout = QHBoxLayout(self._summary)
        summary_layout.setContentsMargins(16, 10, 18, 10)
        summary_layout.setSpacing(16)

        self._queue_map = QLabel()
        self._queue_map.setObjectName("queueMapIcon")
        self._queue_map.setFixedSize(MAP_ICON_SIZE)
        self._queue_map.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(self._queue_map)

        summary_words = QVBoxLayout()
        summary_words.setContentsMargins(0, 0, 0, 0)
        summary_words.setSpacing(2)
        summary_eyebrow = QLabel("FILA SELECIONADA")
        summary_eyebrow.setObjectName("queueSummaryEyebrow")
        summary_words.addWidget(summary_eyebrow)
        self._queue_summary_title = QLabel()
        self._queue_summary_title.setObjectName("queueSummaryTitle")
        summary_words.addWidget(self._queue_summary_title)
        self._queue_summary_map = QLabel()
        self._queue_summary_map.setObjectName("queueSummaryMap")
        summary_words.addWidget(self._queue_summary_map)
        self._queue_summary_detail = QLabel()
        self._queue_summary_detail.setObjectName("queueSummaryDetail")
        summary_words.addWidget(self._queue_summary_detail)
        summary_words.addStretch(1)
        summary_layout.addLayout(summary_words, 1)
        content.addWidget(self._summary)

        helper = QLabel("A opção fica salva e é usada sempre que a automação iniciar.")
        helper.setObjectName("hint")
        content.addWidget(helper)

        self._combo = binder.combo(
            "queue_id",
            [(name, queue_id) for queue_id, name in QUEUES.items()],
            "queueSelector",
        )
        content.addWidget(self._combo)
        self._refresh_queue_summary()

        content.addSpacing(7)
        positions = QFrame()
        positions.setObjectName("optionCard")
        positions_layout = QVBoxLayout(positions)
        positions_layout.setContentsMargins(16, 12, 16, 12)
        positions_layout.setSpacing(7)
        positions_title = QLabel("ROTAS QUE EU QUERO JOGAR")
        positions_title.setObjectName("cardLabel")
        positions_layout.addWidget(positions_title)

        self._primary = self._position_row(
            positions_layout, "Primeira", "primary_position",
            NO_PRIMARY, "primaryPosition",
        )
        self._secondary = self._position_row(
            positions_layout, "Segunda", "secondary_position",
            NO_SECONDARY, "secondaryPosition",
        )
        content.addWidget(positions)

        positions_note = QLabel(
            "O app marca estas rotas no cliente antes de começar a buscar, "
            "e só se elas ainda não estiverem marcadas. Valem para "
            "Ranqueada, Normal Alternada e Flex — as únicas filas que "
            "perguntam a rota. Depois de “Qualquer uma” não existe segunda "
            "opção, e ela não pode repetir a primeira: são regras do próprio "
            "cliente, e a tela já as respeita."
        )
        positions_note.setObjectName("hint")
        positions_note.setWordWrap(True)
        content.addWidget(positions_note)

        self._sync_secondary()
        binder.changed.connect(self._on_config_changed)
        binder.on_reload(self._sync_secondary)
        binder.on_reload(self._refresh_queue_summary)

        content.addSpacing(7)
        behavior = QFrame()
        behavior.setObjectName("optionCard")
        behavior_layout = QVBoxLayout(behavior)
        behavior_layout.setContentsMargins(16, 12, 16, 12)
        behavior_layout.setSpacing(7)
        behavior_title = QLabel("COMPORTAMENTO DA FILA")
        behavior_title.setObjectName("cardLabel")
        behavior_layout.addWidget(behavior_title)
        behavior_layout.addWidget(
            binder.checkbox("Entrar na fila e voltar a ela automaticamente", "auto_queue")
        )
        behavior_layout.addWidget(
            binder.checkbox(
                "Só mexer na fila quando eu for o dono da sala",
                "queue_only_as_host",
            )
        )
        content.addWidget(behavior)

        note = QLabel(
            "Em uma sala de amigo, o dono conduz a busca. Com esta proteção "
            "ligada, o app continua cuidando de aceite, banimento e campeão, "
            "mas não cria sala própria nem muda a fila dele."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        content.addWidget(note)
        layout.addWidget(card)
        layout.addStretch(1)

    def set_unavailable(self, queue_ids) -> None:
        """Marca as filas que o cliente recusa agora.

        A escolha do jogador não é trocada por conta própria: descobrir
        dentro de uma Ranqueada que o app te mudou de fila sozinho seria
        muito pior do que ver a fila marcada aqui.
        """
        model = self._combo.model()
        for index in range(self._combo.count()):
            queue_id = self._combo.itemData(index)
            blocked = queue_id in queue_ids
            name = QUEUES.get(queue_id, str(queue_id))
            suffix = UNAVAILABLE_SUFFIX if blocked else ""
            self._combo.setItemText(index, name + suffix)
            model.item(index).setEnabled(not blocked)

    def _position_row(self, layout, label, attribute, empty, object_name):
        """Uma linha "rota: [lista]", com a opção de não pedir nada.

        A opção vazia vem primeiro porque é o estado de fábrica: quem
        nunca mexeu aqui não quer que o app decida a rota por ele.
        """
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        options = [(empty, "")]
        options += [(preference_name(name), name) for name in PREFERENCE_POSITIONS]
        box = self._binder.combo(attribute, options, object_name)
        self._decorate_positions(box)
        row.addWidget(box)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _on_config_changed(self, attribute: str) -> None:
        if attribute == "primary_position":
            self._sync_secondary()
        if attribute == "queue_id":
            self._refresh_queue_summary()

    @staticmethod
    def _decorate_positions(box) -> None:
        """Põe o símbolo oficial ao lado de cada valor, inclusive o vazio."""
        box.setIconSize(POSITION_ICON_SIZE)
        for index in range(box.count()):
            value = str(box.itemData(index) or "").casefold()
            filename = POSITION_ICONS.get(value, POSITION_ICONS[""])
            box.setItemIcon(
                index,
                QIcon(str(asset_path(f"positions/{filename}"))),
            )

    @staticmethod
    def _active_map_pixmap(filename: str) -> QPixmap:
        """Recorta do sprite o estado colorido e o reduz com suavização."""
        source = QPixmap(str(asset_path(f"maps/{filename}")))
        if source.isNull():
            return source
        # Os assets atuais têm dois quadrados empilhados: ativo em cima e
        # inativo embaixo. Se a Riot trocar o arquivo por um quadrado simples,
        # este recorte continua correto.
        side = min(source.width(), source.height())
        active = source.copy(0, 0, side, side)
        return active.scaled(
            MAP_ICON_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _refresh_queue_summary(self) -> None:
        """Redesenha o resumo a partir da config, inclusive após trocar conta."""
        queue_id = self._binder.config.queue_id
        visual = QUEUE_VISUALS.get(queue_id)
        if visual is None:
            self._queue_map.clear()
            self._queue_summary_title.setText(QUEUES.get(queue_id, f"Fila {queue_id}"))
            self._queue_summary_map.setText("Mapa não identificado")
            self._queue_summary_detail.clear()
            self._queue_map.setToolTip("")
            return

        filename, map_name, detail = visual
        self._queue_map.setPixmap(self._active_map_pixmap(filename))
        self._queue_map.setToolTip(map_name)
        self._queue_summary_title.setText(QUEUES.get(queue_id, f"Fila {queue_id}"))
        self._queue_summary_map.setText(map_name)
        self._queue_summary_detail.setText(detail)

    def _sync_secondary(self) -> None:
        """Deixa a segunda rota coerente com a primeira.

        As duas regras são do cliente, não do app: sem primeira rota — ou
        com “qualquer uma” — não há segunda, e a segunda não repete a
        primeira. A config já endireita isso ao gravar; aqui é para a
        tela não oferecer uma escolha que sumiria sozinha depois.
        """
        primary = self._binder.config.primary_position
        alone = not primary or primary == "fill"
        self._secondary.setEnabled(not alone)
        model = self._secondary.model()
        for index in range(self._secondary.count()):
            value = self._secondary.itemData(index)
            model.item(index).setEnabled(not value or value != primary)
        if (alone or self._binder.config.secondary_position == primary) and (
            self._binder.config.secondary_position
        ):
            self._binder.set("secondary_position", "")
