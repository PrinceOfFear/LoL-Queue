"""Achar o game.cfg em máquinas que não são a de quem escreveu o código.

Estes testes existem por causa de um sintoma real: o app funcionava num
PC e ficava mudo em outro, sem uma linha de diário explicando. A causa
era um caminho fixo na raiz do C: — na máquina que instalou o League em
outro disco, toda leitura devolvia o padrão como se fosse resposta.

Nenhum teste aqui toca o disco de verdade nem depende de ter o jogo
instalado: os candidatos são substituídos por pastas temporárias. Um
teste de descoberta que só passa em quem tem o jogo instalado testa a
máquina, não o código.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lolqueue.vision import gamecfg

CFG = """[General]
WindowMode=0
FlipMiniMap=1
"""


def _instalar(raiz: Path, texto: str = CFG) -> Path:
    """Cria uma instalação de mentira e devolve o game.cfg dela."""
    arquivo = raiz / gamecfg.CONFIG_SUBPATH
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(texto, encoding="utf-8")
    return arquivo


@pytest.fixture(autouse=True)
def _sem_maquina(monkeypatch):
    """Desliga tudo o que consultaria a máquina de verdade.

    Sem isto, um PC com o League aberto acharia a instalação real antes
    da falsa e os testes passariam pelo motivo errado.
    """
    monkeypatch.setattr(gamecfg, "_encontrado", None)
    monkeypatch.setattr(gamecfg, "_from_processes", lambda: iter(()))
    monkeypatch.setattr(gamecfg, "_from_drives", lambda: iter(()))
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", ())


def test_nothing_found_is_reported_as_nothing_found(tmp_path):
    """A resposta honesta para "não achei" é `None`, não um palpite.

    Devolver o caminho provável faria a leitura seguinte falhar em
    silêncio, que é exatamente o defeito que isto conserta.
    """
    assert gamecfg.config_path() is None


def test_the_install_on_another_drive_is_found(tmp_path, monkeypatch):
    """O caso do outro PC: League fora do C:."""
    esperado = _instalar(tmp_path / "D")
    monkeypatch.setattr(
        gamecfg, "_from_drives", lambda: iter([tmp_path / "C", tmp_path / "D"])
    )
    assert gamecfg.config_path() == esperado


def test_a_running_game_outranks_the_likely_places(tmp_path, monkeypatch):
    """Quem está rodando sabe onde está; a lista de sempre é só palpite.

    Importa quando as duas existem — uma instalação antiga esquecida no
    C: e a que o jogador realmente abriu noutro lugar.
    """
    velha = _instalar(tmp_path / "esquecida")
    viva = _instalar(tmp_path / "em-uso")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "esquecida",))
    monkeypatch.setattr(gamecfg, "_from_processes", lambda: iter([tmp_path / "em-uso"]))
    assert gamecfg.config_path() == viva
    assert gamecfg.config_path() != velha


def test_a_directory_without_the_file_does_not_count(tmp_path, monkeypatch):
    """Pasta da Riot vazia — desinstalação parcial — não é uma instalação."""
    (tmp_path / "vazia" / "Config").mkdir(parents=True)
    esperado = _instalar(tmp_path / "boa")
    monkeypatch.setattr(
        gamecfg, "CANDIDATE_DIRS", (tmp_path / "vazia", tmp_path / "boa")
    )
    assert gamecfg.config_path() == esperado


def test_the_options_come_from_the_file_that_was_discovered(tmp_path, monkeypatch):
    """A descoberta serve para alguma coisa: as duas leituras a usam."""
    _instalar(tmp_path / "jogo")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "jogo",))
    assert gamecfg.exclusive_fullscreen() is True
    assert gamecfg.flip_minimap() is True


def test_no_file_means_the_game_defaults(tmp_path):
    """Sem arquivo, o padrão do jogo — e nunca um alarme inventado.

    `exclusive_fullscreen` falso aqui é falta de evidência, não uma
    afirmação; é por isso que a vigilância avisa em separado quando o
    arquivo não foi encontrado.
    """
    assert gamecfg.flip_minimap() is False
    assert gamecfg.exclusive_fullscreen() is False
    assert gamecfg.read_flag("EnableAudioOnMute", default=True) is True
    assert gamecfg.read_number("WindowMode") is None


def test_a_moved_install_is_found_again(tmp_path, monkeypatch):
    """O caminho lembrado que sumiu não pode emudecer o resto da sessão.

    Acontece de verdade quando o jogador reinstala ou move a pasta com o
    app aberto: guardar o caminho velho para sempre trocaria um acerto
    por um erro permanente.
    """
    antigo = _instalar(tmp_path / "antes")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "antes",))
    assert gamecfg.config_path() == antigo

    antigo.unlink()
    novo = _instalar(tmp_path / "depois")
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "depois",))
    assert gamecfg.config_path() == novo


def test_an_explicit_path_still_wins(tmp_path):
    """Quem passa o caminho na mão não passa pela descoberta."""
    arquivo = tmp_path / "meu.cfg"
    arquivo.write_text("WindowMode=2\n", encoding="utf-8")
    assert gamecfg.read_number("WindowMode", arquivo) == gamecfg.WINDOWED
    assert gamecfg.exclusive_fullscreen(arquivo) is False


def test_the_discovery_does_not_repeat_the_same_folder(tmp_path, monkeypatch):
    """Processo e lista costumam apontar para o mesmo lugar.

    Sem a remoção de repetidos, cada pergunta bateria no disco duas ou
    três vezes pela mesma pasta — barato, mas é lixo que cresce junto
    com a lista de candidatos.
    """
    pasta = tmp_path / "jogo"
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (pasta, pasta))
    monkeypatch.setattr(gamecfg, "_from_processes", lambda: iter([pasta]))
    monkeypatch.setattr(gamecfg, "_from_drives", lambda: iter([pasta]))
    assert list(gamecfg.installation_dirs()) == [pasta]


def test_a_broken_process_list_does_not_break_the_discovery(tmp_path, monkeypatch):
    """psutil falhando não pode derrubar a leitura de um arquivo de texto."""

    def explode():
        raise RuntimeError("sem permissão para listar processos")
        yield  # pragma: no cover - inalcançável, mantém a função geradora

    esperado = _instalar(tmp_path / "jogo")
    monkeypatch.setattr(gamecfg, "_from_processes", explode)
    monkeypatch.setattr(gamecfg, "CANDIDATE_DIRS", (tmp_path / "jogo",))
    with pytest.raises(RuntimeError):
        list(gamecfg._from_processes())
    # A descoberta em si não pode propagar isso.
    assert gamecfg.config_path() == esperado
