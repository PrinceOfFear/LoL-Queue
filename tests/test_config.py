from pathlib import Path

import pytest

from lolqueue.config import (
    ACCEPT_DELAY_CEILING,
    DEFAULT_OPGG_TIER,
    OPGG_TIERS,
    POSITIONS,
    QUEUES,
    Config,
)


def test_positions_cover_the_five_lanes():
    assert set(POSITIONS) == {"top", "jungle", "middle", "bottom", "utility"}


def test_pick_list_falls_back_to_the_general_list():
    """Sem lista da posição, vale a geral.

    É o caso do modo cego, que não distribui rota nenhuma, e de quem
    prefere configurar uma lista só.
    """
    config = Config(pick_priority=[64, 11])
    assert config.pick_list("jungle") == [64, 11]
    assert config.pick_list("") == [64, 11]
    assert config.pick_list(None) == [64, 11]


def test_pick_list_prefers_the_list_of_the_assigned_position():
    """Cair de autofill no suporte tem que trocar a lista."""
    config = Config(
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
    )
    assert config.pick_list("utility") == [11]
    assert config.pick_list("top") == [64]


def test_pick_list_ignores_case_from_the_client():
    config = Config(pick_priority=[64], pick_priority_by_position={"bottom": [11]})
    assert config.pick_list("BOTTOM") == [11]


def test_sanitize_drops_unknown_positions_and_malformed_ids():
    config = Config(
        pick_priority_by_position={
            "utility": [11, "x", -3, True],
            "mid": [64],
            "top": [],
        }
    )
    assert config.pick_priority_by_position == {"utility": [11]}


def test_position_lists_round_trip_through_disk(tmp_path):
    path = tmp_path / "config.json"
    original = Config(pick_priority_by_position={"jungle": [64], "bottom": [11]})
    original.save(path)
    assert Config.load(path) == original


def test_defaults_are_conservative():
    config = Config()
    assert config.auto_accept is True
    assert config.auto_queue is False
    assert config.auto_pick is False
    assert config.auto_ban is False
    assert config.queue_id == 420
    assert config.opgg_tier == DEFAULT_OPGG_TIER
    assert (config.lock_delay_min, config.lock_delay_max) == (2.0, 6.0)
    assert (config.accept_delay_min, config.accept_delay_max) == (1.0, 4.0)
    assert (config.postgame_delay_min, config.postgame_delay_max) == (6.0, 10.0)


# ---------- o elo das builds do OP.GG ----------


def test_a_chosen_elo_is_kept():
    assert Config(opgg_tier="challenger").opgg_tier == "challenger"


def test_an_unknown_elo_falls_back_to_the_default():
    """O arquivo é editável à mão; um elo inventado não pode travar o
    app nem seguir escondido até o pedido ao OP.GG falhar em silêncio.
    """
    assert Config(opgg_tier="lendario_supremo").opgg_tier == DEFAULT_OPGG_TIER


def test_every_elo_option_round_trips_through_disk(tmp_path):
    path = tmp_path / "config.json"
    for tier in OPGG_TIERS:
        config = Config(opgg_tier=tier)
        config.save(path)
        assert Config.load(path).opgg_tier == tier


def test_round_trips_through_disk(tmp_path):
    path = tmp_path / "config.json"
    original = Config(auto_queue=True, pick_priority=[64, 11], queue_id=440)
    original.save(path)
    assert Config.load(path) == original


def test_removed_jungle_alert_settings_are_ignored_from_old_configs(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"auto_queue": true, "jungle_callouts": true, "jungle_voice": "old"}',
        encoding="utf-8",
    )

    loaded = Config.load(path)

    assert loaded.auto_queue is True
    assert not hasattr(loaded, "jungle_callouts")
    loaded.save(path)
    assert "jungle_callouts" not in path.read_text(encoding="utf-8")


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


def test_a_save_that_dies_halfway_does_not_take_the_old_config_with_it(
    tmp_path, monkeypatch
):
    """Gravar por cima é o jeito de perder tudo: falta de espaço ou queda
    de energia no meio deixam o arquivo pela metade, e `load` cai nos
    padrões em silêncio — o usuário reabre o app com os ajustes zerados.
    Gravando num temporário e renomeando, ou vale o novo, ou vale o
    velho, nunca um meio-termo ilegível."""
    path = tmp_path / "config.json"
    Config(auto_queue=True).save(path)
    original = path.read_text(encoding="utf-8")

    real = Path.write_text

    def morre_no_meio(self, data, *args, **kwargs):
        # Metade no disco e o resto nunca: é o que sobra de uma gravação
        # interrompida, não importa em qual arquivo ela caia.
        real(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("disco cheio")

    monkeypatch.setattr(Path, "write_text", morre_no_meio)
    with pytest.raises(OSError):
        Config(auto_queue=False).save(path)

    assert path.read_text(encoding="utf-8") == original
    assert Config.load(path).auto_queue is True
    # E o pedaço gravado não fica de lembrança ao lado da config.
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_the_temporary_file_does_not_stay_behind(tmp_path):
    """Sobra de gravação não pode virar lixo permanente ao lado da
    config, nem confundir quem for olhar a pasta."""
    path = tmp_path / "config.json"
    Config().save(path)

    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_queue_catalog_has_the_common_queues():
    assert QUEUES[420] == "Ranqueada Solo/Duo"
    assert 440 in QUEUES and 450 in QUEUES


# ---------- as faixas de atraso ----------


def test_a_backwards_range_is_straightened_on_load():
    """Máximo abaixo do mínimo vira faixa fixa, não erro.

    O arquivo é editável à mão, e um número trocado não pode custar a
    partida — o sorteio já aguenta, mas guardar torto confundiria a UI.
    """
    config = Config(lock_delay_min=6.0, lock_delay_max=2.0)
    assert config.lock_delay_max == 6.0


def test_negative_delays_are_lifted_to_zero():
    config = Config(accept_delay_min=-5.0, accept_delay_max=-1.0)
    assert (config.accept_delay_min, config.accept_delay_max) == (0.0, 0.0)


def test_the_accept_delay_never_outlasts_the_ready_check_window():
    """A janela do "aceitar" dura ~12s; estourá-la perde a partida.

    Vale mesmo para quem editou o arquivo na mão pedindo 60 segundos.
    """
    config = Config(accept_delay_min=30.0, accept_delay_max=60.0)
    assert config.accept_delay_max <= ACCEPT_DELAY_CEILING
    assert config.accept_delay_min <= config.accept_delay_max


def test_the_lock_delay_has_no_such_ceiling():
    """Travar campeão tem turno bem mais longo, e quem quiser 20s pode."""
    config = Config(lock_delay_min=20.0, lock_delay_max=25.0)
    assert config.lock_delay_max == 25.0


def test_the_postgame_wait_is_straightened_like_the_others():
    config = Config(postgame_delay_min=-2.0, postgame_delay_max=3.0)
    assert (config.postgame_delay_min, config.postgame_delay_max) == (0.0, 3.0)
