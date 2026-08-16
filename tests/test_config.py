from lolqueue.config import QUEUES, Config


def test_defaults_are_conservative():
    config = Config()
    assert config.auto_accept is True
    assert config.auto_queue is False
    assert config.auto_pick is False
    assert config.auto_ban is False
    assert config.queue_id == 420
    assert config.lock_delay_seconds == 3.0


def test_round_trips_through_disk(tmp_path):
    path = tmp_path / "config.json"
    original = Config(auto_queue=True, pick_priority=[64, 11], queue_id=440)
    original.save(path)
    assert Config.load(path) == original


def test_missing_file_yields_defaults(tmp_path):
    assert Config.load(tmp_path / "absent.json") == Config()


def test_corrupt_file_yields_defaults_instead_of_crashing(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    assert Config.load(path) == Config()


def test_file_saved_with_a_bom_still_loads(tmp_path):
    """O Notepad do Windows grava UTF-8 com BOM.

    Sem tolerar isso, editar a config na mão apagaria tudo em silêncio.
    """
    path = tmp_path / "config.json"
    path.write_text('{"auto_queue": true}', encoding="utf-8-sig")
    assert Config.load(path).auto_queue is True


def test_garbage_in_a_priority_list_is_dropped(tmp_path):
    """Um id que não é inteiro positivo nunca casa com campeão nenhum.

    Deixar passar só cria um item morto na lista de prioridade, que o
    usuário vê e acha que está valendo.
    """
    path = tmp_path / "config.json"
    path.write_text(
        '{"pick_priority": [64, "x", null, -1, 0, true, 11.5, 266]}',
        encoding="utf-8",
    )
    assert Config.load(path).pick_priority == [64, 266]


def test_a_priority_that_is_not_a_list_becomes_empty(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"ban_priority": 64}', encoding="utf-8")
    assert Config.load(path).ban_priority == []


def test_saving_drops_ids_that_are_not_champion_ids(tmp_path):
    """Lixo não pode nem chegar ao disco, venha de onde vier."""
    path = tmp_path / "config.json"
    config = Config()
    config.ban_priority = [59, "oops", -3]
    config.save(path)
    assert Config.load(path).ban_priority == [59]


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"auto_queue": true, "obsolete": 1}', encoding="utf-8")
    assert Config.load(path).auto_queue is True


def test_save_creates_missing_directories(tmp_path):
    path = tmp_path / "deep" / "nested" / "config.json"
    Config().save(path)
    assert path.exists()


def test_queue_catalog_has_the_common_queues():
    assert QUEUES[420] == "Ranqueada Solo/Duo"
    assert 440 in QUEUES and 450 in QUEUES
