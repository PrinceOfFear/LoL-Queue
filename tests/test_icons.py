from lolqueue.core.icons import AssetStore, IconStore
from lolqueue.lcu.client import LcuError

PNG = b"\x89PNG\r\n\x1a\n"


class FakeClient:
    """Devolve bytes de imagem e anota o que foi pedido."""

    def __init__(self, payload=PNG, raises=None):
        self.payload = payload
        self.raises = raises
        self.paths = []

    def raw(self, path):
        self.paths.append(path)
        if self.raises is not None:
            raise self.raises
        return self.payload


def test_downloads_the_icons_that_are_missing(tmp_path):
    store = IconStore(tmp_path)
    client = FakeClient()

    assert store.fetch_missing(client, [266, 64]) == 2
    assert store.path_for(266).read_bytes() == PNG
    assert store.path_for(64).read_bytes() == PNG


def test_does_not_download_what_is_already_cached(tmp_path):
    """Sem isto o app refaria ~170 requisições a cada abertura."""
    store = IconStore(tmp_path)
    store.path_for(266).write_bytes(PNG)
    client = FakeClient()

    store.fetch_missing(client, [266, 64])
    assert client.paths == [store.url_for(64)]


def test_url_carries_the_champion_id(tmp_path):
    assert IconStore(tmp_path).url_for(266).endswith("/266.png")


def test_a_failed_download_leaves_nothing_behind(tmp_path):
    """Um PNG pela metade no cache ficaria quebrado para sempre."""
    store = IconStore(tmp_path)
    client = FakeClient(raises=LcuError("caiu"))

    assert store.fetch_missing(client, [266]) == 0
    assert not store.has(266)
    assert list(tmp_path.glob("*")) == []


def test_an_empty_response_is_not_cached(tmp_path):
    """Um arquivo de 0 byte viraria um quadrado vazio permanente."""
    store = IconStore(tmp_path)

    assert store.fetch_missing(FakeClient(payload=b""), [266]) == 0
    assert not store.has(266)


def test_has_rejects_a_zero_byte_file(tmp_path):
    store = IconStore(tmp_path)
    store.path_for(266).write_bytes(b"")
    assert store.has(266) is False


def test_missing_lists_only_what_is_absent(tmp_path):
    store = IconStore(tmp_path)
    store.path_for(266).write_bytes(PNG)
    assert store.missing([266, 64, 51]) == [64, 51]


def test_stops_early_when_asked_to(tmp_path):
    """Fechar a janela no meio do download não pode travar o fechamento."""
    store = IconStore(tmp_path)
    client = FakeClient()

    store.fetch_missing(client, [266, 64, 51], should_continue=lambda: False)
    assert client.paths == []


# --- as imagens guardadas pelo caminho (ícones de runa) -------------------

AERY = "/lol-game-data/assets/v1/perk-images/Styles/Sorcery/SummonAery/SummonAery.png"
PRECISION = "/lol-game-data/assets/v1/perk-images/Styles/7201_Precision.png"


def test_an_asset_is_cached_under_a_name_of_its_own(tmp_path):
    store = AssetStore(tmp_path)
    client = FakeClient()

    assert store.fetch_missing(client, [AERY]) == 1
    assert store.path_for(AERY).read_bytes() == PNG


def test_two_assets_with_the_same_file_name_do_not_collide(tmp_path):
    """Cada árvore tem uma pasta própria na origem, e nomes de arquivo
    se repetem entre elas. Guardar só o nome final deixava uma imagem
    sobrescrevendo a outra — a árvore errada apareceria na tela."""
    store = AssetStore(tmp_path)
    precision = "/lol-game-data/assets/v1/perk-images/Styles/Precision/p8000.png"
    sorcery = "/lol-game-data/assets/v1/perk-images/Styles/Sorcery/p8000.png"

    assert store.path_for(precision) != store.path_for(sorcery)


def test_a_cached_asset_is_not_downloaded_again(tmp_path):
    store = AssetStore(tmp_path)
    client = FakeClient()
    store.fetch_missing(client, [AERY])

    store.fetch_missing(client, [AERY, PRECISION])
    assert client.paths == [AERY, PRECISION]


def test_a_failed_asset_download_leaves_nothing_behind(tmp_path):
    store = AssetStore(tmp_path)

    assert store.fetch_missing(FakeClient(raises=LcuError("caiu")), [AERY]) == 0
    assert not store.has(AERY)
    assert list(tmp_path.glob("*")) == []


def test_an_empty_asset_is_not_cached(tmp_path):
    store = AssetStore(tmp_path)

    assert store.fetch_missing(FakeClient(payload=b""), [AERY]) == 0
    assert not store.has(AERY)


def test_an_empty_url_is_never_asked_for(tmp_path):
    """Runa sem ícone no catálogo não vira uma requisição a lugar nenhum."""
    store = AssetStore(tmp_path)
    client = FakeClient()

    store.fetch_missing(client, ["", AERY])
    assert client.paths == [AERY]
