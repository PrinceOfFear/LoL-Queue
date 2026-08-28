from lolqueue.config import Config
from lolqueue.core.champ_select import (
    MAX_LOCK_ATTEMPTS,
    ChampSelectController,
    find_current_action,
    local_position,
)
from lolqueue.core.champions import ChampionCatalog
from lolqueue.lcu import endpoints
from tests.fakes import FakeLcuClient

SUMMARY = [
    {"id": 64, "name": "Lee Sin", "alias": "LeeSin"},
    {"id": 11, "name": "Master Yi", "alias": "MasterYi"},
]


def session(action_type="pick", completed=False, in_progress=True, actor=0):
    return {
        "localPlayerCellId": 0,
        "actions": [
            [
                {
                    "id": 7,
                    "actorCellId": actor,
                    "championId": 0,
                    "completed": completed,
                    "isInProgress": in_progress,
                    "type": action_type,
                }
            ]
        ],
    }


def ban_session(prior=()):
    """Sessão na vez de banir, após ações já concluídas de outros jogadores.

    `prior` é uma lista de (tipo, championId) — o que já saiu de jogo
    antes da nossa vez.
    """
    concluidas = [
        {
            "id": 100 + indice,
            "actorCellId": 5 + indice,
            "championId": champion_id,
            "completed": True,
            "isInProgress": False,
            "type": tipo,
        }
        for indice, (tipo, champion_id) in enumerate(prior)
    ]
    minha = {
        "id": 7,
        "actorCellId": 0,
        "championId": 0,
        "completed": False,
        "isInProgress": True,
        "type": "ban",
    }
    return {"localPlayerCellId": 0, "actions": [concluidas, [minha]]}


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def settled_session(champion_id, action_id=7, action_type="pick"):
    """Sessão depois que o cliente fechou a nossa ação.

    `champion_id` é o que ficou de fato registrado — que nem sempre é o
    que mandamos.
    """
    return {
        "localPlayerCellId": 0,
        "actions": [
            [
                {
                    "id": action_id,
                    "actorCellId": 0,
                    "championId": champion_id,
                    "completed": True,
                    "isInProgress": False,
                    "type": action_type,
                }
            ]
        ],
    }


def make_controller(
    config, responses, log=None, rng=None, on_pick_predicted=None, antitoxic=None
):
    responses = {endpoints.CHAMPION_SUMMARY: SUMMARY, **responses}
    client = FakeLcuClient(responses=responses)
    catalog = ChampionCatalog(client)
    catalog.load()
    clock = Clock()
    extra = {} if rng is None else {"rng": rng}
    if on_pick_predicted is not None:
        extra["on_pick_predicted"] = on_pick_predicted
    if antitoxic is not None:
        extra["antitoxic"] = antitoxic
    controller = ChampSelectController(
        client, config, catalog, log=log, now=clock, **extra
    )
    return controller, client, clock


def locks(client):
    """Só os PATCH que tentam travar a ação."""
    return [body for _, body in client.payloads if body.get("completed")]


# Sem espera para declarar a intenção: o que estes testes medem é o
# conteúdo do PATCH, e a espera tem testes próprios em test_pick_intent.
PICK_CONFIG = Config(
    auto_pick=True,
    pick_priority=[64, 11],
    lock_delay_min=3.0,
    lock_delay_max=3.0,
    pick_intent_delay=0.0,
)


def test_finds_our_in_progress_action():
    assert find_current_action(session())["id"] == 7


def test_ignores_another_players_action():
    assert find_current_action(session(actor=3)) is None


def test_ignores_completed_action():
    assert find_current_action(session(completed=True)) is None


def test_ignores_action_not_in_progress():
    assert find_current_action(session(in_progress=False)) is None


def test_hovers_the_first_available_pick():
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    path, body = client.payloads[-1]
    assert path == endpoints.CHAMP_SELECT_ACTION.format(action_id=7)
    assert body == {"championId": 64}


def test_falls_through_to_the_next_when_first_is_taken():
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [11],
        },
    )
    controller.tick()
    _, body = client.payloads[-1]
    assert body == {"championId": 11}


def test_does_not_lock_before_the_delay():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 2.0
    controller.tick()
    assert all(body.get("completed") is not True for _, body in client.payloads)


def test_locks_after_the_delay():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    assert client.payloads[-1][1] == {"championId": 64, "completed": True}


def test_hovers_only_once_while_waiting():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 1.0
    controller.tick()
    clock.value = 2.0
    controller.tick()
    hovers = [b for _, b in client.payloads if b == {"championId": 64}]
    assert len(hovers) == 1


def test_no_available_champion_locks_nothing_and_warns():
    messages = []
    responses = {
        endpoints.CHAMPION_SUMMARY: SUMMARY,
        endpoints.CHAMP_SELECT_SESSION: session(),
        endpoints.PICKABLE_CHAMPIONS: [99],
    }
    client = FakeLcuClient(responses=responses)
    catalog = ChampionCatalog(client)
    catalog.load()
    controller = ChampSelectController(
        client, PICK_CONFIG, catalog, log=messages.append, now=Clock()
    )
    controller.tick()
    assert client.payloads == []
    assert messages


def test_ban_uses_the_ban_list():
    config = Config(auto_ban=True, ban_priority=[11], lock_delay_min=0.0, lock_delay_max=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: session(action_type="ban"),
            endpoints.BANNABLE_CHAMPIONS: [11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_ban_works_even_when_the_client_reports_no_bannable_ids():
    """O cliente responde `[-1]` em `bannable-champion-ids`.

    Filtrar por essa lista deixava o banimento sempre vazio: nenhum id
    real casa com o sentinela, então a vez de banir passava em branco.
    Quem pode ser banido sai da própria sessão.
    """
    config = Config(auto_ban=True, ban_priority=[11], lock_delay_min=0.0, lock_delay_max=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_ban_skips_a_champion_already_banned():
    config = Config(auto_ban=True, ban_priority=[64, 11], lock_delay_min=0.0, lock_delay_max=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("ban", 64)]),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_ban_skips_a_champion_already_picked():
    """O segundo turno de bans acontece com campeões já escolhidos.

    Banir um deles é recusado pelo cliente.
    """
    config = Config(auto_ban=True, ban_priority=[64, 11], lock_delay_min=0.0, lock_delay_max=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("pick", 64)]),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_a_ban_that_passed_does_not_block_the_champion():
    """Uma vez de banir que expira fica registrada com `championId` -1.

    Isso não tira campeão nenhum de jogo.
    """
    config = Config(auto_ban=True, ban_priority=[64], lock_delay_min=0.0, lock_delay_max=0.0)
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("ban", -1)]),
            endpoints.BANNABLE_CHAMPIONS: [-1],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 64}


def test_does_not_hover_again_after_locking():
    """A sessão ainda anuncia a ação em andamento logo depois do lock.

    Sem lembrar do que já travou, o tick seguinte refazia o hover — o
    registro mostrava a mesma escolha duas vezes.
    """
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    depois_do_lock = len(client.payloads)
    clock.value = 4.0
    controller.tick()
    assert len(client.payloads) == depois_do_lock


def test_only_reports_the_lock_after_the_client_records_it():
    """O 2xx do PATCH não prova nada.

    Numa ranqueada de verdade o banimento respondeu sem erro, o app
    anunciou "confirmado" e a sessão fechou a ação com -1: ninguém foi
    banido. Quem decide se deu certo é a sessão, não a resposta.
    """
    mensagens = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    assert not any("confirmado" in m for m in mensagens)

    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(64)
    clock.value = 3.75
    controller.tick()
    assert any("Lee Sin confirmado" in m for m in mensagens)


def test_warns_when_the_client_ignored_the_lock():
    """Vez de banir que passou em branco fica registrada com -1."""
    mensagens = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(-1)
    clock.value = 3.75
    controller.tick()
    assert any("não registrou" in m for m in mensagens)
    assert not any("confirmado" in m for m in mensagens)


def test_reports_the_champion_the_client_actually_recorded():
    """Se fechou com outro campeão, o registro precisa dizer qual."""
    mensagens = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(11)
    clock.value = 3.75
    controller.tick()
    assert any("Master Yi" in m for m in mensagens)


def test_retries_the_lock_while_the_client_ignores_it():
    """Enquanto a ação continuar aberta, insiste.

    O cliente engole a primeira trava quando a fase de ban ainda está
    abrindo. Sem reenviar, a vez passa em branco.
    """
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    assert len(locks(client)) == 1
    clock.value = 4.6
    controller.tick()
    assert len(locks(client)) == 2


def test_gives_up_after_repeated_lock_attempts():
    """Insistir para sempre viraria enxurrada de PATCH no cliente."""
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    for extra in range(1, MAX_LOCK_ATTEMPTS + 10):
        clock.value = 3.5 + extra * 1.5
        controller.tick()
    assert len(locks(client)) == MAX_LOCK_ATTEMPTS


def test_pick_skips_a_champion_someone_else_already_took():
    """A lista de escolhíveis pode demorar a refletir o pick alheio."""
    config = Config(auto_pick=True, pick_priority=[64, 11], lock_delay_min=0.0, lock_delay_max=0.0)
    tomado = ban_session([("pick", 64)])
    tomado["actions"][1][0]["type"] = "pick"
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: tomado,
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def positioned_session(position):
    """Sessão na vez de escolher, com a rota já atribuída."""
    data = session()
    data["myTeam"] = [{"cellId": 0, "assignedPosition": position}]
    return data


def test_reads_the_assigned_position_of_the_local_player():
    assert local_position(positioned_session("utility")) == "utility"


def test_no_position_when_the_mode_does_not_assign_one():
    """Cego e coop não distribuem rota: `assignedPosition` vem vazio."""
    assert local_position(positioned_session("")) == ""
    assert local_position(session()) == ""


def test_picks_from_the_list_of_the_assigned_position():
    """Autofill no suporte precisa usar a lista de suporte."""
    config = Config(
        auto_pick=True,
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
        lock_delay_min=0.0, lock_delay_max=0.0,
    )
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: positioned_session("utility"),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 11}


def test_picks_from_the_general_list_when_the_position_has_none():
    config = Config(
        auto_pick=True,
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
        lock_delay_min=0.0, lock_delay_max=0.0,
    )
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: positioned_session("jungle"),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )
    controller.tick()
    assert client.payloads[0][1] == {"championId": 64}


def test_announces_the_assigned_position_once():
    """O usuário precisa ver de que rota veio a lista usada."""
    mensagens = []
    config = Config(
        auto_pick=True,
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
        lock_delay_min=0.0, lock_delay_max=0.0,
    )
    controller, client, clock = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: positioned_session("utility"),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        log=mensagens.append,
    )
    controller.tick()
    clock.value = 1.0
    controller.tick()
    anuncios = [m for m in mensagens if "Suporte" in m]
    assert len(anuncios) == 1


def test_auto_pick_off_means_no_action_on_pick():
    controller, client, _ = make_controller(
        Config(auto_pick=False, pick_priority=[64]),
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    assert client.payloads == []


def test_reset_clears_hover_state_between_games():
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
    )
    controller.tick()
    controller.reset()
    clock.value = 10.0
    controller.tick()
    hovers = [b for _, b in client.payloads if b == {"championId": 64}]
    assert len(hovers) == 2


# ---------- o atraso antes de travar ----------

DELAY_CONFIG = Config(
    auto_pick=True, pick_priority=[64], lock_delay_min=2.0, lock_delay_max=6.0
)
PICK_SESSION = {
    endpoints.CHAMP_SELECT_SESSION: session(),
    endpoints.PICKABLE_CHAMPIONS: [64, 11],
}


def test_the_lock_delay_is_drawn_from_the_configured_range():
    pedidos = []
    controller, _, _ = make_controller(
        DELAY_CONFIG,
        PICK_SESSION,
        rng=lambda low, high: pedidos.append((low, high)) or 4.0,
    )

    controller.tick()

    assert pedidos == [(2.0, 6.0)]


def test_the_champion_is_shown_for_the_whole_drawn_delay():
    """O hover é o que o time vê. Travar antes da hora encurta isso."""
    controller, client, clock = make_controller(
        DELAY_CONFIG, PICK_SESSION, rng=lambda low, high: 5.0
    )

    controller.tick()
    assert client.payloads[-1][1] == {"championId": 64}, "nem mostrou"
    assert locks(client) == [], "travou sem mostrar"

    clock.value += 4.9
    controller.tick()
    assert locks(client) == [], "travou antes do sorteado"

    clock.value += 0.2
    controller.tick()
    assert locks(client), "não travou depois do sorteado"


def test_the_announced_time_is_the_one_actually_waited():
    """Anunciar 3s e travar em 5 seria pior que não anunciar nada."""
    messages = []
    controller, _, _ = make_controller(
        DELAY_CONFIG, PICK_SESSION, log=messages.append, rng=lambda low, high: 5.0
    )

    controller.tick()

    assert any("5s" in m for m in messages), messages


def test_the_ban_waits_the_drawn_delay_too():
    """Banir também é hover primeiro: o time vê o alvo antes de fechar."""
    controller, client, clock = make_controller(
        Config(
            auto_ban=True, ban_priority=[64], lock_delay_min=2.0, lock_delay_max=6.0
        ),
        {endpoints.CHAMP_SELECT_SESSION: session(action_type="ban")},
        rng=lambda low, high: 5.0,
    )

    controller.tick()
    assert client.payloads[-1][1] == {"championId": 64}
    assert locks(client) == []

    clock.value += 5.1
    controller.tick()
    assert locks(client)


def test_each_action_draws_its_own_delay():
    """Duas ações no mesmo compasso é justamente o que se quer evitar."""
    pedidos = []
    controller, _, clock = make_controller(
        DELAY_CONFIG,
        PICK_SESSION,
        rng=lambda low, high: pedidos.append((low, high)) or 2.0,
    )

    controller.tick()
    clock.value += 3.0
    controller.tick()
    controller.reset()
    controller.tick()

    assert len(pedidos) == 2


def test_the_ban_announces_itself_as_a_ban():
    """"Selecionando" num ban esconde o ban no meio dos picks.

    O registro do usuário passou o dia inteiro sem uma linha sequer que
    dissesse "ban" com um campeão junto; quando o ban enfim funciona,
    ele precisa se distinguir do pick à primeira vista.
    """
    mensagens = []
    controller, _, _ = make_controller(
        Config(auto_ban=True, ban_priority=[64], lock_delay_min=3.0,
               lock_delay_max=3.0),
        {endpoints.CHAMP_SELECT_SESSION: ban_session()},
        log=mensagens.append,
    )

    controller.tick()

    assert mensagens == ["Banindo Lee Sin — travando em 3s."]


# ---------- a vez de banir passada em branco ----------


SEM_LISTA = Config(auto_ban=True, ban_priority=[], lock_delay_min=3.0,
                   lock_delay_max=3.0)


def test_an_empty_ban_list_never_touches_the_client():
    """Não existe operação da LCU que feche essa vez mais cedo.

    O PATCH com championId 0 responde 2xx, mas o cliente nunca fecha a
    ação com ele — só o relógio da própria fase de ban faz isso. Foi
    medido em partida real: confirmação chegando 15 a 40s depois do
    aviso, o mesmo tempo que o cronômetro de ban leva para zerar
    sozinho. Insistir só enche o cliente de requisição atoa.
    """
    controller, client, clock = make_controller(
        SEM_LISTA, {endpoints.CHAMP_SELECT_SESSION: ban_session()}
    )

    for _ in range(30):
        controller.tick()
        clock.value += 1.0

    assert client.payloads == []


def test_an_empty_ban_list_announces_itself_once():
    mensagens = []
    controller, client, clock = make_controller(
        SEM_LISTA,
        {endpoints.CHAMP_SELECT_SESSION: ban_session()},
        log=mensagens.append,
    )

    for _ in range(10):
        controller.tick()
        clock.value += 1.0

    avisos = [m for m in mensagens if "Sem campeão" in m]
    assert len(avisos) == 1, mensagens


def test_passing_the_turn_no_longer_asks_for_a_manual_ban():
    """O aviso de hoje é para quem tem lista e ficou sem opção."""
    mensagens = []
    controller, _, clock = make_controller(
        SEM_LISTA,
        {endpoints.CHAMP_SELECT_SESSION: ban_session()},
        log=mensagens.append,
    )

    controller.tick()

    assert not any("Escolha manualmente" in m for m in mensagens), mensagens


def test_a_list_with_everyone_taken_still_asks_for_a_manual_ban():
    """Quem escolheu campeões quer banir; ficar sem opção é acidente."""
    mensagens = []
    controller, client, clock = make_controller(
        Config(auto_ban=True, ban_priority=[64], lock_delay_min=0.0,
               lock_delay_max=0.0),
        {endpoints.CHAMP_SELECT_SESSION: ban_session(prior=[("ban", 64)])},
        log=mensagens.append,
    )

    controller.tick()
    clock.value += 3.0
    controller.tick()

    assert client.payloads == []
    assert any("Escolha manualmente" in m for m in mensagens), mensagens


def test_an_empty_pick_list_never_picks_nothing():
    """Passar a vez é só do ban: um pick em branco perde o campeão."""
    controller, client, clock = make_controller(
        Config(auto_pick=True, pick_priority=[]),
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
    )

    controller.tick()
    clock.value += 3.0
    controller.tick()

    assert client.payloads == []


def test_the_blank_turn_is_reported_as_asked_for():
    """Passar a vez é resultado, não falha: o relato tem que dizer isso.

    A confirmação só chega quando o cliente fecha a ação sozinho — é
    ele quem decide a hora, não o app.
    """
    mensagens = []
    controller, client, clock = make_controller(
        SEM_LISTA,
        {endpoints.CHAMP_SELECT_SESSION: ban_session()},
        log=mensagens.append,
    )

    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(
        -1, action_type="ban"
    )
    controller.tick()

    assert mensagens[-1] == "Vez de banir passada em branco."


def test_a_manual_ban_during_the_wait_is_still_reported():
    """Enquanto o app espera, o jogador pode banir na mão — vale contar."""
    mensagens = []
    controller, client, clock = make_controller(
        SEM_LISTA,
        {endpoints.CHAMP_SELECT_SESSION: ban_session()},
        log=mensagens.append,
    )

    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(
        64, action_type="ban"
    )
    controller.tick()

    assert "Lee Sin" in mensagens[-1]
    assert "não ficou em branco" in mensagens[-1]


# ---------- prévia de quem vai ser escolhido ----------


def test_predicts_the_top_of_the_priority_list():
    """A prévia usa a mesma lista que a trava de verdade usaria."""
    previstos = []
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == [64]


def test_prediction_skips_a_champion_already_taken():
    previstos = []
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("ban", 64)]),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == [11]


def test_prediction_only_fires_when_it_changes():
    previstos = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    clock.value = 1.0
    controller.tick()
    assert previstos == [64]


def test_prediction_updates_as_the_top_choice_gets_banned():
    """Ao vivo: se banirem o topo da lista no meio da seleção, a prévia troca."""
    previstos = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = ban_session([("ban", 64)])
    clock.value = 1.0
    controller.tick()
    assert previstos == [64, 11]


def test_prediction_respects_the_assigned_position_list():
    previstos = []
    config = Config(
        auto_pick=True,
        pick_priority=[64],
        pick_priority_by_position={"utility": [11]},
    )
    controller, client, _ = make_controller(
        config,
        {
            endpoints.CHAMP_SELECT_SESSION: positioned_session("utility"),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == [11]


def test_no_prediction_without_a_champion_left():
    previstos = []
    controller, client, _ = make_controller(
        Config(auto_pick=True, pick_priority=[64]),
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session([("ban", 64)]),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == []


def test_the_preview_survives_a_pickable_list_that_did_not_come():
    """Lista vazia é "não sei", e não "nenhum campeão vale".

    Este teste nasceu de uma suspeita que a medição depois derrubou: eu
    achava que o cliente só povoava `pickable-champion-ids` na hora do
    pick. Uma seleção real gravada mostra a lista inteira já no
    `BAN_PICK` — 173 campeões —, então não é isso que apaga a prévia.

    O teste fica porque o caso que ele cobre continua existindo: a rota
    pode falhar, e aí `_available` devolve conjunto vazio. Filtrar por
    esse vazio zeraria a prévia sem que nada de fato a desqualificasse.
    """
    previstos = []
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == [64]


def test_the_preview_survives_a_pickable_route_that_answers_404():
    """O mesmo, quando a rota nem responde — é o que ela faz fora da
    janela em que o cliente a mantém de pé."""
    previstos = []
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {endpoints.CHAMP_SELECT_SESSION: ban_session()},
        on_pick_predicted=previstos.append,
    )
    client.failures.add(endpoints.PICKABLE_CHAMPIONS)
    controller.tick()
    assert previstos == [64]


def test_a_known_pickable_list_still_filters_the_preview():
    """A folga vale só quando a lista é desconhecida. Existindo lista,
    um campeão fora dela continua não sendo previsto — senão a prévia
    prometeria um campeão que o jogador nem tem."""
    previstos = []
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == [11]


def test_auto_pick_off_never_predicts():
    previstos = []
    controller, client, _ = make_controller(
        Config(auto_pick=False, pick_priority=[64]),
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [64],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == []


def test_reset_clears_the_prediction_and_announces_it():
    """Trocar de partida não pode deixar o boneco da anterior na tela."""
    previstos = []
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == [64]
    controller.reset()
    assert previstos == [64, None]


def test_prediction_freezes_once_the_real_pick_locks():
    """Depois que o pick de verdade tranca, a prévia não pode pular pro
    próximo da lista só porque o campeão travado passou a contar como
    "já tirado" na sessão — senão o boneco mostrado trocaria bem na
    hora em que a escolha real acabou de sair.
    """
    previstos = []
    controller, client, clock = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    clock.value = 3.5
    controller.tick()
    client.responses[endpoints.CHAMP_SELECT_SESSION] = settled_session(64)
    clock.value = 3.75
    controller.tick()
    assert previstos == [64]


def test_prediction_resyncs_to_none_when_the_real_pick_finds_nothing():
    """O cache de pickáveis da prévia pode ficar desatualizado.

    A prévia usa `_pickable()`, buscado uma vez e guardado; o pick real
    sempre busca de novo. Se a lista encolher entre uma coisa e outra
    (ex.: o campeão saiu de moda no meio da seleção) e não sobrar
    candidato nenhum na hora de escolher de verdade, a prévia não pode
    continuar mostrando o boneco antigo — precisa cair pra "nenhum",
    igual ao que o pick real vai fazer.
    """
    previstos = []
    controller, client, _ = make_controller(
        PICK_CONFIG,
        {
            endpoints.CHAMP_SELECT_SESSION: ban_session(),
            endpoints.PICKABLE_CHAMPIONS: [64, 11],
        },
        on_pick_predicted=previstos.append,
    )
    controller.tick()
    assert previstos == [64]

    client.responses[endpoints.CHAMP_SELECT_SESSION] = session()
    client.responses[endpoints.PICKABLE_CHAMPIONS] = []
    controller.tick()

    assert previstos == [64, None]


def test_reset_without_a_prior_prediction_stays_quiet():
    previstos = []
    controller, client, _ = make_controller(
        Config(auto_pick=False),
        {endpoints.CHAMP_SELECT_SESSION: ban_session()},
        on_pick_predicted=previstos.append,
    )
    controller.reset()
    assert previstos == []
