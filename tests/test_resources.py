"""Onde ficam os arquivos que não são código.

Dentro do `.exe` o pacote não é uma pasta no disco: o PyInstaller
descompacta tudo num diretório temporário e conta em `sys._MEIPASS`.
Um caminho montado a partir de `__file__` aponta para dentro do
arquivo compactado e não abre.
"""

import sys
from types import SimpleNamespace

from lolqueue import resources


def test_the_icon_travels_with_the_package():
    assert resources.icon_path().parts[-2:] == ("assets", "icon.ico")


def test_the_icon_file_is_really_there():
    """O ícone é versionado; `tools/make_icon.py` o regera."""
    assert resources.icon_path().is_file()


def test_the_interface_background_travels_with_the_package():
    assert resources.background_path().parts[-2:] == ("assets", "rift-at-dusk.png")
    assert resources.background_path().is_file()


def test_inside_the_exe_it_reads_from_the_unpacked_folder(tmp_path, monkeypatch):
    (tmp_path / "lolqueue" / "assets").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resources.icon_path() == tmp_path / "lolqueue" / "assets" / "icon.ico"
    assert resources.background_path() == tmp_path / "lolqueue" / "assets" / "rift-at-dusk.png"


def test_inside_the_nuitka_binary_it_reads_from_where_it_was_extracted(tmp_path, monkeypatch):
    """Nuitka expõe o diretório extraído em `__compiled__.containing_dir`.

    Não em `sys.argv[0]`: em modo onefile isso continua apontando pro
    binário que o usuário abriu, não pra pasta temporária de extração
    — usar argv[0] aqui reproduziria o bug do ícone/fundo sumindo.
    """
    (tmp_path / "lolqueue" / "assets").mkdir(parents=True)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    # argv[0] deliberadamente apontando pra outro lugar, pra provar que
    # não é ele que resources.py deve seguir.
    monkeypatch.setattr(sys, "argv", ["C:/nao-e-aqui/LoL Queue.exe"])
    main = sys.modules["__main__"]
    compiled = SimpleNamespace(containing_dir=str(tmp_path))
    monkeypatch.setattr(main, "__compiled__", compiled, raising=False)

    assert resources.icon_path() == tmp_path / "lolqueue" / "assets" / "icon.ico"


def test_the_binary_falls_back_to_the_folder_next_to_the_exe(tmp_path, monkeypatch):
    """Se `containing_dir` mentir, valem os dados ao lado do executável.

    Foi o que aconteceu no build standalone: o ícone da barra de tarefas
    sumiu porque o caminho anunciado não era onde o Nuitka tinha posto
    `lolqueue/assets`. Escolher o primeiro candidato que existe de
    verdade é o que impede o app de apontar pro vazio.
    """
    ao_lado = tmp_path / "dist"
    (ao_lado / "lolqueue" / "assets").mkdir(parents=True)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    main = sys.modules["__main__"]
    mentira = SimpleNamespace(containing_dir=str(tmp_path / "lugar-nenhum"))
    monkeypatch.setattr(main, "__compiled__", mentira, raising=False)
    monkeypatch.setattr(sys, "executable", str(ao_lado / "LoL Queue.exe"))

    assert resources.icon_path() == ao_lado / "lolqueue" / "assets" / "icon.ico"


def test_with_nothing_on_disk_it_still_answers_the_bundled_path(tmp_path, monkeypatch):
    """Sem nenhum candidato real, responde o primeiro — não explode.

    Preferir o que existe não pode virar uma busca que termina sem
    resposta: quando nada existe, quem chama merece o caminho mais
    provável, pra falha aparecer como "arquivo faltando" e não como
    caminho absurdo vindo de outro lugar.
    """
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "sumiu"), raising=False)
    monkeypatch.setattr(resources, "__file__", str(tmp_path / "fonte-sumiu" / "resources.py"))

    assert resources.icon_path() == tmp_path / "sumiu" / "lolqueue" / "assets" / "icon.ico"


def test_outside_the_exe_it_reads_from_the_source_tree(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert resources.icon_path().is_file()


def test_the_icon_offers_a_png_alternative_to_the_ico(tmp_path, monkeypatch):
    """Depois do `.ico` vem o `.png`, na mesma pasta de assets.

    Ler `.ico` no Qt depende do plugin `qico`; `.png` o Qt decodifica
    sozinho, sem plugin nenhum. Empacotado, o plugin é justamente o que
    pode faltar — então o PNG existe como rede de segurança para o
    ícone não sumir da barra de tarefas.
    """
    (tmp_path / "lolqueue" / "assets").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assets = tmp_path / "lolqueue" / "assets"
    assert resources.icon_candidates() == [assets / "icon.ico", assets / "icon.png"]


def test_the_icon_candidates_start_with_the_icon_path():
    """O primeiro candidato é o mesmo caminho que `icon_path()` já dava."""
    assert resources.icon_candidates()[0] == resources.icon_path()


def test_the_png_icon_ships_with_the_source():
    """O PNG precisa existir de verdade, senão a rede de segurança é ilusão."""
    assert resources.icon_candidates()[1].is_file()
