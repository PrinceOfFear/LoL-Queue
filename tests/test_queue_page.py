"""O seletor de fila diante de filas que a Riot desligou.

Some com a opção? Não: o jogador procuraria por ela e acharia que o app
quebrou. Fica visível, marcada e sem poder ser escolhida — o motivo
aparece junto.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from lolqueue import config as config_module  # noqa: E402
from lolqueue.config import Config  # noqa: E402
from lolqueue.ui.binding import ConfigBinder  # noqa: E402
from lolqueue.ui.pages.queue import QueuePage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def page(app, monkeypatch, tmp_path):
    # Trocar a fila grava a config na hora, e a do usuário não pode ser
    # tocada por um teste.
    monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "config.json")
    return QueuePage(ConfigBinder(Config(queue_id=420), None))


def item(page, queue_id):
    combo = page._combo
    return combo.model().item(combo.findData(queue_id))


def test_an_unavailable_queue_says_so(page):
    page.set_unavailable({430})

    assert "indisponível" in item(page, 430).text()


def test_an_unavailable_queue_cannot_be_chosen(page):
    page.set_unavailable({430})

    assert not item(page, 430).isEnabled()


def test_the_other_queues_stay_as_they_were(page):
    page.set_unavailable({430})

    assert item(page, 420).text() == "Ranqueada Solo/Duo"
    assert item(page, 420).isEnabled()


def test_a_queue_that_comes_back_is_usable_again(page):
    """A Riot religa fila; reconectar tem que refletir isso."""
    page.set_unavailable({430})
    page.set_unavailable(set())

    assert item(page, 430).text() == "Normal Blind"
    assert item(page, 430).isEnabled()


def test_the_chosen_queue_is_not_swapped_behind_the_players_back(page):
    """Trocar a fila escolhida sozinho seria pior que avisar.

    O jogador pediu Normal Blind; se o app o jogasse em Ranqueada por
    conta própria, descobriria dentro da partida.
    """
    page._combo.setCurrentIndex(page._combo.findData(430))

    page.set_unavailable({430})

    assert page._combo.currentData() == 430
    assert page._binder.config.queue_id == 430


def test_every_position_choice_uses_an_original_role_icon(page):
    for combo in (page._primary, page._secondary):
        assert all(not combo.itemIcon(index).isNull() for index in range(combo.count()))


def test_the_queue_summary_starts_on_the_selected_map(page):
    assert page._queue_summary_title.text() == "Ranqueada Solo/Duo"
    assert page._queue_summary_map.text() == "Summoner's Rift"
    assert page._queue_map.pixmap() is not None
    assert not page._queue_map.pixmap().isNull()


def test_changing_queue_redraws_its_map_and_description(page):
    page._combo.setCurrentIndex(page._combo.findData(450))

    assert page._queue_summary_title.text() == "ARAM"
    assert page._queue_summary_map.text() == "Howling Abyss"
    assert "uma única rota" in page._queue_summary_detail.text()
