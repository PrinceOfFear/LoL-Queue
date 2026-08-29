import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue.ui.widgets.loadout_studio import (  # noqa: E402
    RANK_COMBO_ICON_SIZE,
    RankPreview,
    SpellKeyPreview,
    decorate_rank_combo,
)
from lolqueue import config as config_module  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.ui.binding import ConfigBinder  # noqa: E402
from lolqueue.ui.pages.settings import SettingsPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_auto_mode_is_explicitly_a_simulation_decided_by_the_account(app):
    preview = SpellKeyPreview()

    assert preview.objectName() == "spellSimulation"
    assert preview.property("keyMode") == "auto"
    assert preview.property("simulated") == "true"
    assert preview.badge_label.text() == "SIMULAÇÃO"
    assert "conta decide" in preview.status_label.text().casefold()
    assert "simulação" in preview.note_label.text().casefold()
    assert {preview.d_slot.spell, preview.f_slot.spell} == {"flash", "barrier"}

    for slot in (preview.d_slot, preview.f_slot):
        assert slot.objectName() == "spellSlot"
        assert slot.key_label.objectName() == "keyCap"
        assert slot.icon_label.objectName() == "spellIcon"
        assert slot.icon_label.pixmap() is not None
        assert not slot.icon_label.pixmap().isNull()


def test_fixed_modes_put_flash_on_the_requested_key(app):
    preview = SpellKeyPreview()

    preview.set_key("d")
    assert preview.d_slot.spell == "flash"
    assert preview.f_slot.spell == "barrier"
    assert preview.d_slot.property("isFlash") == "true"
    assert preview.property("simulated") == "false"

    preview.set_key("F")
    assert preview.d_slot.spell == "barrier"
    assert preview.f_slot.spell == "flash"
    assert preview.f_slot.property("isFlash") == "true"
    assert preview.status_label.text() == "Barreira no D · Flash no F"


def test_unknown_flash_key_is_rejected(app):
    with pytest.raises(ValueError):
        SpellKeyPreview().set_key("space")


def test_plus_tier_reuses_the_base_crest_and_trims_transparent_margin(app):
    preview = RankPreview()
    preview.set_tier("gold_plus", "Ouro+")

    assert preview.tier == "gold_plus"
    assert preview.base_tier == "gold"
    assert preview.property("plus") == "true"
    assert preview.title_label.text() == "Ouro+"
    assert preview.subtitle_label.text() == "OURO E ELOS SUPERIORES"

    crest = preview.crest_label.pixmap()
    assert crest is not None and not crest.isNull()
    # O arquivo fonte é 16:9 com o brasão pequeno ao centro. Depois do
    # recorte, o emblema fica aproximadamente quadrado e ocupa o preview.
    assert crest.height() >= crest.width() * 0.75


def test_all_uses_its_own_crest_and_description(app):
    preview = RankPreview()
    preview.set_tier("all", "Todos os elos")

    assert preview.base_tier == "all"
    assert preview.subtitle_label.text() == "TODAS AS FAIXAS COMPETITIVAS"
    assert not preview.crest_label.pixmap().isNull()


def test_rank_combo_is_decorated_from_each_items_data(app):
    combo = QtWidgets.QComboBox()
    combo.addItem("Todos os elos", "all")
    combo.addItem("Ouro+", "gold_plus")
    combo.addItem("Desafiante", "challenger")

    decorate_rank_combo(combo)

    assert combo.iconSize() == RANK_COMBO_ICON_SIZE
    assert combo.property("rankDecorated") == "true"
    assert all(not combo.itemIcon(index).isNull() for index in range(combo.count()))


def test_settings_connect_the_real_config_to_both_visual_previews(
    app, monkeypatch, tmp_path
):
    monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "config.json")
    config = Config(opgg_tier="grandmaster", flash_key="d")
    binder = ConfigBinder(config)
    page = SettingsPage(binder)

    assert page._rank_preview.tier == "grandmaster"
    assert page._rank_preview.title_label.text() == "Grão-Mestre"
    assert page._spell_preview.d_slot.spell == "flash"
    assert page._spell_preview.f_slot.spell == "barrier"

    page._tier.setCurrentIndex(page._tier.findData("emerald_plus"))
    page._flash.setCurrentIndex(page._flash.findData("f"))

    assert config.opgg_tier == "emerald_plus"
    assert page._rank_preview.base_tier == "emerald"
    assert config.flash_key == "f"
    assert page._spell_preview.f_slot.spell == "flash"

    # Troca de conta muda a config por baixo da tela e chama reload.
    config.opgg_tier = "silver"
    config.flash_key = "auto"
    binder.reload()

    assert page._rank_preview.base_tier == "silver"
    assert page._spell_preview.property("simulated") == "true"
