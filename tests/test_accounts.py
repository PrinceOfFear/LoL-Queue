"""Perfis por conta: herdar da principal, lembrar de quem já veio."""

from __future__ import annotations

import json

import pytest

from lolqueue.config import Config
from lolqueue.core.accounts import (
    ARRIVED_FIRST,
    ARRIVED_INHERITED,
    ARRIVED_KNOWN,
    Account,
    Accounts,
    account_key,
)
from lolqueue.core.identity import Identity


def quem(nome: str = "Thiago", tag: str = "BR1", regiao: str = "BR") -> Identity:
    return Identity(game_name=nome, tag_line=tag, region=regiao, level=300)


def relogio(marcas: list[str]):
    """Um relógio de mentira que anda a cada leitura."""
    passos = iter(marcas)
    return lambda: next(passos, marcas[-1])


def test_the_first_account_becomes_the_main_one():
    """Quem chega primeiro vira a principal sem ninguém pedir."""
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    chegada = contas.arrive(quem(), Config())
    assert chegada.kind == ARRIVED_FIRST
    assert chegada.main
    assert contas.main == account_key(quem())


def test_the_first_account_keeps_what_was_on_screen():
    """Quem já usava o app não perde os ajustes ao ganhar perfis."""
    config = Config(queue_id=440, flash_key="f")
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), config)
    assert config.queue_id == 440
    assert config.flash_key == "f"
    assert contas.accounts[contas.main].settings["flash_key"] == "f"


def test_a_new_account_inherits_from_the_main_one():
    """Conta emprestada abre com o app do dono do PC, não zerada."""
    config = Config(queue_id=440, flash_key="f", primary_position="jungle")
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), config)

    config.queue_id = 400  # o outro jogador mexeu antes de trocar de conta
    chegada = contas.arrive(quem("Amigo", "BR2"), config)

    assert chegada.kind == ARRIVED_INHERITED
    assert chegada.source == "Thiago#BR1"
    assert not chegada.main
    assert config.queue_id == 440
    assert config.primary_position == "jungle"


def test_a_known_account_gets_its_own_settings_back():
    """Voltar para uma conta já vista devolve o que era dela."""
    config = Config(flash_key="d")
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), config)

    amigo = quem("Amigo", "BR2")
    contas.arrive(amigo, config)
    config.flash_key = "f"
    contas.remember(account_key(amigo), config)

    contas.arrive(quem(), config)
    assert config.flash_key == "d"

    chegada = contas.arrive(amigo, config)
    assert chegada.kind == ARRIVED_KNOWN
    assert config.flash_key == "f"


def test_changing_the_case_of_the_name_is_not_another_account():
    """O jogador pode trocar a caixa do Riot ID sem virar outra pessoa."""
    assert account_key(quem("Thiago")) == account_key(quem("THIAGO"))


def test_the_same_name_in_another_region_is_another_account():
    """Riot ID igual em servidor diferente é outra conta mesmo."""
    assert account_key(quem(regiao="BR")) != account_key(quem(regiao="EUW"))


def test_settings_from_an_unknown_field_are_ignored():
    """Perfil gravado por versão mais nova não derruba a mais velha."""
    contas = Accounts(
        main="chave",
        accounts={"chave": Account(label="Velha", settings={"inventado": 1})},
    )
    config = Config()
    contas.arrive(quem("Nova", "BR9"), config)
    assert not hasattr(config, "inventado")


def test_a_broken_profile_does_not_break_the_config():
    """Perfil com valor torto vira padrão, como o disco já fazia."""
    contas = Accounts(
        main="chave",
        accounts={"chave": Account(label="Velha", settings={"flash_key": "z"})},
    )
    config = Config()
    contas.arrive(quem("Nova", "BR9"), config)
    assert config.flash_key == "auto"


def test_remembering_an_unknown_account_registers_nothing():
    """Sem o cliente aberto não há nome nem região — não inventa conta."""
    contas = Accounts()
    assert not contas.remember("ninguem", Config())
    assert len(contas) == 0


def test_deleting_the_main_account_leaves_the_post_empty():
    """Herdar da conta errada é pior do que não herdar."""
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config())
    contas.arrive(quem("Amigo", "BR2"), Config())
    assert contas.forget(account_key(quem()))
    assert contas.main == ""


def test_the_main_account_comes_first_then_the_most_recent():
    """A ordem da tela: a principal, depois quem entrou por último."""
    contas = Accounts(now=relogio(["2026-01-01T00:00:00", "2026-01-02T00:00:00",
                                   "2026-01-03T00:00:00"]))
    contas.arrive(quem("Velha", "BR1"), Config())
    contas.arrive(quem("Meio", "BR2"), Config())
    contas.arrive(quem("Nova", "BR3"), Config())
    assert [conta.label for _, conta in contas.ordered()] == [
        "Velha#BR1",
        "Nova#BR3",
        "Meio#BR2",
    ]


def test_a_saved_history_comes_back_whole(tmp_path):
    """O que foi gravado é o que volta na próxima abertura."""
    alvo = tmp_path / "contas.json"
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config(queue_id=440))
    contas.arrive(quem("Amigo", "BR2"), Config())
    contas.save(alvo)

    lidas = Accounts.load(alvo)
    assert lidas.main == contas.main
    assert len(lidas) == 2
    assert lidas.accounts[lidas.main].settings["queue_id"] == 440


def test_a_corrupt_history_starts_empty(tmp_path):
    """Arquivo ilegível não vira erro na cara de quem só quer jogar."""
    alvo = tmp_path / "contas.json"
    alvo.write_text("{isso não é json", encoding="utf-8")
    assert len(Accounts.load(alvo)) == 0


def test_a_missing_history_starts_empty(tmp_path):
    assert len(Accounts.load(tmp_path / "nao-existe.json")) == 0


def test_a_main_pointing_nowhere_is_dropped(tmp_path):
    """Principal apontando para conta apagada à mão não herda nada."""
    alvo = tmp_path / "contas.json"
    alvo.write_text(
        json.dumps({"main": "fantasma", "accounts": {}}), encoding="utf-8"
    )
    assert Accounts.load(alvo).main == ""


def test_marking_an_unknown_account_as_main_does_nothing():
    contas = Accounts()
    assert not contas.set_main("ninguem")
    assert contas.main == ""


def test_a_half_written_history_is_never_left_behind(tmp_path):
    """Falha na gravação não deixa o pedaço ao lado do arquivo bom."""
    alvo = tmp_path / "sem-permissao" / "contas.json"
    alvo.parent.mkdir()
    contas = Accounts(now=lambda: "2026-01-01T00:00:00")
    contas.arrive(quem(), Config())

    original = alvo.parent.__class__.replace

    def falhar(self, target):  # noqa: ANN001
        raise OSError("disco cheio")

    alvo.parent.__class__.replace = falhar
    try:
        with pytest.raises(OSError):
            contas.save(alvo)
    finally:
        alvo.parent.__class__.replace = original
    assert list(alvo.parent.iterdir()) == []
