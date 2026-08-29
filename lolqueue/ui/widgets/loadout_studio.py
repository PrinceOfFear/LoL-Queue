"""Prévias visuais para as escolhas de feitiço e elo.

Os widgets deste módulo não conhecem a configuração do app. Eles recebem o
valor já escolhido, desenham a consequência e expõem nomes/propriedades
estáveis para o QSS e para testes. Os assets passam por :func:`asset_path`
para continuarem funcionando tanto no fonte quanto no executável empacotado.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap, QRegion
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...resources import asset_path

SPELL_ICON_SIZE = QSize(48, 48)
RANK_PREVIEW_ICON_SIZE = QSize(124, 112)
RANK_COMBO_ICON_SIZE = QSize(30, 30)

_SPELLS = {
    "flash": ("Flash", "spells/flash.png"),
    "barrier": ("Barreira", "spells/barrier.png"),
}


def _repolish(widget: QWidget) -> None:
    """Atualiza seletores QSS baseados em propriedades dinâmicas."""

    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _spell_pixmap(spell: str) -> QPixmap:
    pixmap = QPixmap(str(asset_path(_SPELLS[spell][1])))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        SPELL_ICON_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class _SpellSlot(QFrame):
    """Uma tecla e o feitiço que a prévia colocou nela."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key.upper()
        self.spell = ""
        self.setObjectName("spellSlot")
        self.setProperty("key", self.key.lower())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(116)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 11)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.key_label = QLabel(self.key)
        self.key_label.setObjectName("keyCap")
        self.key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_label.setFixedSize(28, 24)
        top.addWidget(self.key_label)
        top.addStretch(1)
        layout.addLayout(top)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("spellIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(SPELL_ICON_SIZE)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.name_label = QLabel()
        self.name_label.setObjectName("spellName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label)

    def set_spell(self, spell: str) -> None:
        if spell not in _SPELLS:
            raise ValueError(f"Feitiço desconhecido: {spell!r}")

        self.spell = spell
        name, _ = _SPELLS[spell]
        pixmap = _spell_pixmap(spell)
        if pixmap.isNull():
            self.icon_label.clear()
        else:
            self.icon_label.setPixmap(pixmap)
        self.icon_label.setAccessibleName(f"Ícone de {name}")
        self.icon_label.setToolTip(name)
        self.name_label.setText(name)
        self.setProperty("spell", spell)
        self.setProperty("isFlash", "true" if spell == "flash" else "false")
        _repolish(self)


class SpellKeyPreview(QWidget):
    """Simula Flash e Barreira nos slots D/F.

    Em ``auto`` a disposição desenhada é deliberadamente identificada como
    simulação: o app respeita o lado do Flash que já estiver salvo na conta.
    Nos modos ``d`` e ``f`` a prévia representa uma ordem fixa.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spellSimulation")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.key_mode = "auto"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        self.badge_label = QLabel()
        self.badge_label.setObjectName("spellSimulationBadge")
        heading.addWidget(self.badge_label)
        heading.addStretch(1)
        layout.addLayout(heading)

        slots = QHBoxLayout()
        slots.setContentsMargins(0, 0, 0, 0)
        slots.setSpacing(10)
        self.d_slot = _SpellSlot("D")
        self.f_slot = _SpellSlot("F")
        slots.addWidget(self.d_slot)

        self.swap_label = QLabel()
        self.swap_label.setObjectName("spellSwapIndicator")
        self.swap_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.swap_label.setPixmap(
            QIcon(str(asset_path("ui-swap.svg"))).pixmap(QSize(22, 22))
        )
        self.swap_label.setAccessibleName("Ordem dos feitiços")
        slots.addWidget(self.swap_label)
        slots.addWidget(self.f_slot)
        layout.addLayout(slots)

        self.status_label = QLabel()
        self.status_label.setObjectName("spellSimulationTitle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.note_label = QLabel()
        self.note_label.setObjectName("spellSimulationNote")
        self.note_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)

        self.set_key("auto")

    def set_key(self, key: str) -> None:
        """Atualiza a simulação para ``auto``, ``d`` ou ``f``."""

        normalized = str(key).strip().casefold()
        if normalized not in {"auto", "d", "f"}:
            raise ValueError("A tecla do Flash deve ser 'auto', 'd' ou 'f'")

        self.key_mode = normalized
        if normalized == "d":
            d_spell, f_spell = "flash", "barrier"
            badge = "ORDEM FIXA"
            status = "Flash no D · Barreira no F"
            note = "A recomendação será aplicada nesta ordem."
        elif normalized == "f":
            d_spell, f_spell = "barrier", "flash"
            badge = "ORDEM FIXA"
            status = "Barreira no D · Flash no F"
            note = "A recomendação será aplicada nesta ordem."
        else:
            # Uma composição reconhecível para explicar a escolha sem fingir
            # que esta será necessariamente a ordem encontrada na conta.
            d_spell, f_spell = "barrier", "flash"
            badge = "SIMULAÇÃO"
            status = "A conta decide onde fica o Flash"
            note = "Simulação: a ordem abaixo é apenas uma prévia."

        self.d_slot.set_spell(d_spell)
        self.f_slot.set_spell(f_spell)
        self.badge_label.setText(badge)
        self.status_label.setText(status)
        self.note_label.setText(note)
        self.setProperty("keyMode", normalized)
        self.setProperty("simulated", "true" if normalized == "auto" else "false")
        self.setAccessibleName(status)
        _repolish(self)


def _normalize_tier(tier: object) -> str:
    normalized = str(tier or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized.endswith("+"):
        normalized = normalized[:-1].rstrip("_") + "_plus"
    return normalized


def _rank_asset_tier(tier: object) -> str:
    """Converte variantes ``*_plus`` no brasão do elo-base."""

    normalized = _normalize_tier(tier)
    if normalized.endswith("_plus"):
        return normalized.removesuffix("_plus")
    return normalized


def _trim_transparent(pixmap: QPixmap) -> QPixmap:
    """Remove a grande moldura transparente presente nos brasões oficiais."""

    if pixmap.isNull() or not pixmap.hasAlphaChannel():
        return pixmap
    mask = pixmap.mask()
    if mask.isNull():
        return pixmap
    bounds = QRegion(mask).boundingRect()
    if bounds.isEmpty() or bounds == pixmap.rect():
        return pixmap
    return pixmap.copy(bounds)


def _rank_pixmap(asset_tier: str) -> QPixmap:
    if not asset_tier:
        return QPixmap()
    source = QPixmap(str(asset_path(f"ranks/{asset_tier}.png")))
    return _trim_transparent(source)


def rank_pixmap(tier: object, size: QSize | None = None) -> QPixmap:
    """Devolve o brasão-base de ``tier``, opcionalmente já redimensionado."""

    pixmap = _rank_pixmap(_rank_asset_tier(tier))
    if pixmap.isNull() or size is None:
        return pixmap
    return pixmap.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def rank_icon(tier: object, size: QSize = RANK_COMBO_ICON_SIZE) -> QIcon:
    """Ícone reutilizável para botões, combos e cartões de histórico."""

    pixmap = rank_pixmap(tier, size)
    return QIcon(pixmap) if not pixmap.isNull() else QIcon()


class RankPreview(QWidget):
    """Brasão e explicação da faixa de elo escolhida para a build."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rankPreview")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tier = ""
        self.base_tier = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.crest_label = QLabel()
        self.crest_label.setObjectName("rankCrest")
        self.crest_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crest_label.setFixedSize(RANK_PREVIEW_ICON_SIZE)
        layout.addWidget(self.crest_label)

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(4)
        words.addStretch(1)
        self.title_label = QLabel()
        self.title_label.setObjectName("rankTitle")
        words.addWidget(self.title_label)
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("rankSubtitle")
        self.subtitle_label.setWordWrap(True)
        words.addWidget(self.subtitle_label)
        words.addStretch(1)
        layout.addLayout(words, 1)

        self.set_tier("all", "Todos os elos")

    def set_tier(self, tier: object, label: str) -> None:
        normalized = _normalize_tier(tier)
        base_tier = _rank_asset_tier(normalized)
        title = str(label or normalized.replace("_plus", "+").replace("_", " ").title())
        plus = normalized.endswith("_plus")

        pixmap = rank_pixmap(base_tier)
        if pixmap.isNull():
            self.crest_label.clear()
            subtitle = "BRASÃO INDISPONÍVEL"
        else:
            self.crest_label.setPixmap(
                pixmap.scaled(
                    RANK_PREVIEW_ICON_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            if normalized == "all":
                subtitle = "TODAS AS FAIXAS COMPETITIVAS"
            elif plus:
                subtitle = f"{title.removesuffix('+').strip().upper()} E ELOS SUPERIORES"
            else:
                subtitle = "BUILD RECOMENDADA PARA ESTE ELO"

        self.tier = normalized
        self.base_tier = base_tier
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.crest_label.setAccessibleName(f"Brasão {title}")
        self.crest_label.setToolTip(title)
        self.setProperty("tier", normalized)
        self.setProperty("baseTier", base_tier)
        self.setProperty("plus", "true" if plus else "false")
        self.crest_label.setProperty("tier", base_tier)
        self.setAccessibleName(f"Elo das builds: {title}")
        _repolish(self)
        _repolish(self.crest_label)


def decorate_rank_combo(combo: QComboBox) -> None:
    """Adiciona a cada item o brasão indicado pelo seu ``itemData``."""

    combo.setIconSize(RANK_COMBO_ICON_SIZE)
    for index in range(combo.count()):
        asset_tier = _rank_asset_tier(combo.itemData(index))
        combo.setItemIcon(index, rank_icon(asset_tier))
    combo.setProperty("rankDecorated", "true")
    _repolish(combo)


__all__ = [
    "RankPreview",
    "SpellKeyPreview",
    "decorate_rank_combo",
    "rank_icon",
    "rank_pixmap",
]
