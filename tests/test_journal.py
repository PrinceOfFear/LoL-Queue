"""Registro em arquivo.

O painel da janela guarda 400 linhas em memória e some ao fechar o app,
mas é o único lugar que diz qual lista o motor usou, se o banimento
entrou e se a fila travou. Depois da partida, que é quando se quer
conferir, não havia mais nada para ler.
"""

from datetime import date

import pytest

from lolqueue.core.journal import Journal


@pytest.fixture
def clock():
    return lambda: "12:34:56"


def test_a_message_lands_in_the_file_of_the_day(tmp_path, clock):
    journal = Journal(tmp_path, clock=clock, today=lambda: date(2026, 8, 18))

    journal.write("Entrando na fila.")

    assert (tmp_path / "2026-08-18.log").read_text(encoding="utf-8") == (
        "12:34:56  Entrando na fila.\n"
    )


def test_messages_pile_up_instead_of_replacing_each_other(tmp_path, clock):
    journal = Journal(tmp_path, clock=clock, today=lambda: date(2026, 8, 18))

    journal.write("primeira")
    journal.write("segunda")

    lines = (tmp_path / "2026-08-18.log").read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["primeira", "segunda"]


def test_the_directory_is_created_on_demand(tmp_path, clock):
    target = tmp_path / "fundo" / "registro"
    journal = Journal(target, clock=clock, today=lambda: date(2026, 8, 18))

    journal.write("oi")

    assert (target / "2026-08-18.log").exists()


def test_a_new_day_starts_a_new_file(tmp_path, clock):
    day = {"value": date(2026, 8, 18)}
    journal = Journal(tmp_path, clock=clock, today=lambda: day["value"])

    journal.write("ontem")
    day["value"] = date(2026, 8, 19)
    journal.write("hoje")

    assert (tmp_path / "2026-08-18.log").read_text(encoding="utf-8").strip().endswith(
        "ontem"
    )
    assert (tmp_path / "2026-08-19.log").read_text(encoding="utf-8").strip().endswith(
        "hoje"
    )


def test_old_files_are_dropped(tmp_path, clock):
    """Sem poda o diretório cresceria para sempre."""
    (tmp_path / "2026-07-01.log").write_text("velho", encoding="utf-8")
    (tmp_path / "2026-08-17.log").write_text("recente", encoding="utf-8")

    Journal(tmp_path, clock=clock, today=lambda: date(2026, 8, 18), keep_days=14)

    assert not (tmp_path / "2026-07-01.log").exists()
    assert (tmp_path / "2026-08-17.log").exists()


def test_files_that_are_not_ours_are_left_alone(tmp_path, clock):
    """Podar por data no nome, nunca por varrer o diretório inteiro."""
    (tmp_path / "anotacoes.txt").write_text("minhas", encoding="utf-8")
    (tmp_path / "sem-data.log").write_text("qualquer", encoding="utf-8")

    Journal(tmp_path, clock=clock, today=lambda: date(2026, 8, 18), keep_days=1)

    assert (tmp_path / "anotacoes.txt").exists()
    assert (tmp_path / "sem-data.log").exists()


def test_a_broken_disk_does_not_take_the_app_down(tmp_path, clock, monkeypatch):
    """Registro é conveniência: falhar ao gravar não pode derrubar nada."""
    journal = Journal(tmp_path, clock=clock, today=lambda: date(2026, 8, 18))

    def explode(*args, **kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr("pathlib.Path.open", explode)

    journal.write("some")  # não levanta

    assert journal.failed is True


def test_it_stops_trying_after_it_fails(tmp_path, clock, monkeypatch):
    """Insistir a cada linha travaria a janela num disco doente."""
    journal = Journal(tmp_path, clock=clock, today=lambda: date(2026, 8, 18))
    calls = []

    def explode(*args, **kwargs):
        calls.append(1)
        raise OSError("disco cheio")

    monkeypatch.setattr("pathlib.Path.open", explode)

    journal.write("uma")
    journal.write("outra")

    assert len(calls) == 1
