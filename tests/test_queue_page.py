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
