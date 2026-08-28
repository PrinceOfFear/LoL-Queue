"""Os retratos do Data Dragon virando molde para procurar no minimapa.

Nada aqui toca a internet: a rede é injetada, e os PNG são montados no
próprio teste. O codificador de teste existe porque o decodificador do
app é escrito à mão — usar uma biblioteca para gerar o arquivo e outra
para conferir esconderia justamente o erro que interessa, que é o de
desfazer os filtros de linha do PNG.
"""

import json
import struct
import zlib

import numpy as np
import pytest

from lolqueue.vision.icons import (
    ChampionIcons,
    Template,
    circular_mask,
    decode_png,
    normalize_name,
    resize,
)


# --- codificador de PNG só para os testes ------------------------------


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _filter_row(row: bytes, prev: bytes, bpp: int, kind: int) -> bytes:
    """Aplica um dos cinco filtros de linha do PNG, como manda a norma."""
    out = bytearray()
    for i, value in enumerate(row):
        left = row[i - bpp] if i >= bpp else 0
        up = prev[i]
        upleft = prev[i - bpp] if i >= bpp else 0
        if kind == 0:
            pred = 0
        elif kind == 1:
            pred = left
        elif kind == 2:
            pred = up
        elif kind == 3:
            pred = (left + up) >> 1
        else:
            pred = _paeth(left, up, upleft)
        out.append((value - pred) & 0xFF)
    return bytes(out)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def encode_png(pixels: np.ndarray, filters: int | list[int] = 0) -> bytes:
    """PNG de 8 bits, sem entrelaçamento, com os filtros pedidos."""
    height, width, channels = pixels.shape
    color = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    raw = bytearray()
    stride = width * channels
    prev = bytes(stride)
    kinds = [filters] * height if isinstance(filters, int) else filters
    for y in range(height):
        row = pixels[y].tobytes()
        kind = kinds[y % len(kinds)]
        raw.append(kind)
        raw += _filter_row(row, prev, channels, kind)
        prev = row
    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _chunk(b"IEND", b"")
    )


@pytest.fixture
def retrato() -> np.ndarray:
    """Um retrato falso, mas com variação em toda parte.

    Molde chapado casaria com qualquer coisa e não provaria nada.
    """
    rng = np.random.default_rng(7)
    return rng.integers(0, 256, (24, 24, 3), dtype=np.uint8)


# --- decodificação -----------------------------------------------------


def test_a_png_survives_the_round_trip(retrato):
    assert np.array_equal(decode_png(encode_png(retrato)), retrato)


@pytest.mark.parametrize("filtro", [0, 1, 2, 3, 4])
def test_every_row_filter_is_undone(retrato, filtro):
    """Os cinco filtros aparecem em arquivo real, misturados na mesma imagem."""
    assert np.array_equal(decode_png(encode_png(retrato, filtro)), retrato)


def test_filters_mixed_within_one_image_are_undone(retrato):
    dados = encode_png(retrato, [0, 4, 2, 1, 3])
    assert np.array_equal(decode_png(dados), retrato)


def test_the_alpha_channel_is_dropped(retrato):
    com_alfa = np.dstack([retrato, np.full((24, 24), 200, np.uint8)])
    decodificado = decode_png(encode_png(com_alfa, 4))
    assert decodificado.shape == (24, 24, 3)
    assert np.array_equal(decodificado, retrato)


def test_a_gray_png_becomes_three_equal_channels():
    cinza = np.arange(16, dtype=np.uint8).reshape(4, 4, 1)
    decodificado = decode_png(encode_png(cinza, 2))
    assert decodificado.shape == (4, 4, 3)
    assert np.array_equal(decodificado[:, :, 0], decodificado[:, :, 2])


@pytest.mark.parametrize(
    "lixo",
    [b"", b"nao sou png", b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40],
)
def test_garbage_decodes_to_nothing_instead_of_exploding(lixo):
    """Cache corrompido é rotina; derrubar a thread do aviso não é."""
    assert decode_png(lixo) is None


# --- preparo do molde --------------------------------------------------


def test_shrinking_averages_instead_of_sampling():
    """Amostrar um pixel a cada N joga fora o desenho do ícone.

    O retrato tem 120 px e no minimapa aparece com ~20: sem média, o
    molde vira ruído e a correlação não fecha em canto nenhum.
    """
    imagem = np.zeros((4, 4, 3), np.uint8)
    imagem[:, :2] = 0
    imagem[:, 2:] = 200
    menor = resize(imagem, 2)
    assert menor.shape == (2, 2, 3)
    assert np.allclose(menor[:, 0], 0.0)
    assert np.allclose(menor[:, 1], 200.0)


def test_shrinking_keeps_a_flat_color_flat():
    imagem = np.full((30, 30, 3), 77, np.uint8)
    assert np.allclose(resize(imagem, 7), 77.0)


def test_the_mask_keeps_the_middle_and_throws_the_ring_away():
    """O ícone no minimapa é redondo e tem um anel da cor do time.

    O anel é a única parte que muda entre o mesmo campeão nos dois
    times; deixá-lo dentro da conta faria o molde do inimigo casar pior
    justamente quando ele é inimigo.
    """
    mascara = circular_mask(21)
    assert mascara[10, 10]
    assert not mascara[0, 0]
    assert not mascara[0, 10]
    assert not mascara[10, 20]
    assert mascara.mean() < np.pi / 4


def test_the_template_carries_pixels_and_mask_of_the_same_size(retrato):
    molde = Template.from_portrait(retrato, 12)
    assert molde.pixels.shape == (12, 12, 3)
    assert molde.mask.shape == (12, 12)
    assert molde.energy > 0.0


def test_the_template_ignores_what_is_outside_the_mask(retrato):
    """Dois moldes que só diferem fora da máscara têm que ser idênticos."""
    outro = retrato.copy()
    outro[0, 0] = (255, 0, 255)
    outro[-1, -1] = (0, 255, 0)
    a = Template.from_portrait(retrato, 16)
    b = Template.from_portrait(outro, 16)
    assert np.allclose(a.centered, b.centered)


# --- nomes -------------------------------------------------------------


@pytest.mark.parametrize(
    "nome,esperado",
    [
        ("Lee Sin", "leesin"),
        ("Kai'Sa", "kaisa"),
        ("Nunu & Willump", "nunuwillump"),
        ("Dr. Mundo", "drmundo"),
        ("Renata Glasc", "renataglasc"),
    ],
)
def test_names_normalize_to_something_comparable(nome, esperado):
    assert normalize_name(nome) == esperado


# --- rede injetada -----------------------------------------------------


VERSAO = "14.10.1"


class RedeFalsa:
    """Data Dragon de mentira. Guarda quantas vezes cada URL foi pedida."""

    def __init__(self, retrato: np.ndarray, campeoes=None) -> None:
        self.pedidos: list[str] = []
        self.retrato = retrato
        self.campeoes = campeoes or {
            "MonkeyKing": {"id": "MonkeyKing", "name": "Wukong"},
            "LeeSin": {"id": "LeeSin", "name": "Lee Sin"},
        }
        self.falhas: set[str] = set()

    def __call__(self, url: str) -> bytes | None:
        self.pedidos.append(url)
        if any(marca in url for marca in self.falhas):
            return None
        if url.endswith("versions.json"):
            return json.dumps([VERSAO, "14.9.1"]).encode()
        if url.endswith("champion.json"):
            return json.dumps({"data": self.campeoes}).encode()
        if url.endswith(".png"):
            return encode_png(self.retrato)
        return None


def test_the_icon_is_downloaded_once_and_then_read_from_disk(tmp_path, retrato):
    """Baixar o mesmo retrato a cada quadro derrubaria o laço de aviso."""
    rede = RedeFalsa(retrato)
    icones = ChampionIcons(directory=tmp_path, fetch=rede)

    primeiro = icones.template("Lee Sin", 16)
    assert primeiro is not None
    baixados = [u for u in rede.pedidos if u.endswith(".png")]

    outro = ChampionIcons(directory=tmp_path, fetch=rede)
    assert outro.template("Lee Sin", 16) is not None
    assert [u for u in rede.pedidos if u.endswith(".png")] == baixados


def test_the_template_is_reused_between_calls(tmp_path, retrato):
    rede = RedeFalsa(retrato)
    icones = ChampionIcons(directory=tmp_path, fetch=rede)
    assert icones.template("Lee Sin", 16) is icones.template("Lee Sin", 16)


def test_the_display_name_finds_the_data_dragon_key(tmp_path, retrato):
    """Wukong se chama MonkeyKing no arquivo, e só o catálogo sabe disso."""
    rede = RedeFalsa(retrato)
    icones = ChampionIcons(directory=tmp_path, fetch=rede)
    assert icones.key_for("Wukong") == "MonkeyKing"
    assert icones.template("Wukong", 16) is not None
    assert any("MonkeyKing.png" in u for u in rede.pedidos)


def test_without_the_catalog_the_name_is_guessed_instead_of_given_up(
    tmp_path, retrato
):
    """Catálogo fora do ar não pode calar o aviso para todo mundo.

    O palpite acerta a maioria dos campeões — erra os poucos cujo nome
    de arquivo não sai do nome de tela, e para esses o molde não vem.
    """
    rede = RedeFalsa(retrato)
    rede.falhas.add("champion.json")
    icones = ChampionIcons(directory=tmp_path, fetch=rede)
    assert icones.key_for("Lee Sin") == "LeeSin"
    assert icones.template("Lee Sin", 16) is not None


def test_the_network_being_down_yields_nothing_instead_of_exploding(tmp_path):
    icones = ChampionIcons(directory=tmp_path, fetch=lambda url: None)
    assert icones.template("Lee Sin", 16) is None


def test_a_fetch_that_raises_is_swallowed(tmp_path):
    def rede(url):
        raise RuntimeError("sem rede")

    icones = ChampionIcons(directory=tmp_path, fetch=rede)
    assert icones.template("Lee Sin", 16) is None


def test_a_corrupt_cached_icon_is_downloaded_again(tmp_path, retrato):
    rede = RedeFalsa(retrato)
    icones = ChampionIcons(directory=tmp_path, fetch=rede)
    assert icones.template("Lee Sin", 16) is not None

    (tmp_path / "LeeSin.png").write_bytes(b"pela metade")
    outro = ChampionIcons(directory=tmp_path, fetch=rede)
    assert outro.template("Lee Sin", 16) is not None
    assert len([u for u in rede.pedidos if u.endswith("LeeSin.png")]) == 2


def test_an_empty_champion_name_asks_nothing(tmp_path, retrato):
    rede = RedeFalsa(retrato)
    icones = ChampionIcons(directory=tmp_path, fetch=rede)
    assert icones.template("", 16) is None
