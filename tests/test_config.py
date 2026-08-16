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
