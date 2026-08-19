"""Runas e feitiços automáticos, a partir da recomendação da Riot.

Duas regras guiam quase tudo aqui:

- o lado do Flash é hábito muscular do jogador, não preferência da
  Riot: a recomendação pode vir com ele invertido, e trocá-lo de tecla
  na véspera da partida é pior do que não fazer nada;
- página de runas é do usuário. O app cria e apaga a *sua* página, e
  jamais encosta nas outras.
"""

import threading
import time

from lolqueue.config import Config
from lolqueue.core.champions import ChampionCatalog
from lolqueue.core.loadout import PAGE_PREFIX, Loadout, align_spells
from lolqueue.core.opgg import Build as OpggBuild
from lolqueue.lcu import endpoints
from tests.fakes import FakeLcuClient

SUMMARY = [{"id": 96, "name": "Kog Maw", "alias": "KogMaw"}]

PERK_IDS = [8008, 9111, 9103, 8299, 8429, 8451, 5005, 5008, 5001]

RECOMMENDATION = {
    "primaryPerkStyleId": 8000,
    "secondaryPerkStyleId": 8400,
    "summonerSpellIds": [21, 4],
    "perks": [{"id": perk} for perk in PERK_IDS],
}

MY_PAGE = {"id": 1, "name": PAGE_PREFIX + ": Kog Maw", "isDeletable": True}
USER_PAGE = {"id": 2, "name": "Blitz: Kog Maw ADC", "isDeletable": True}


def recommended_path(champion_id=96, position="BOTTOM", map_id=11):
    return endpoints.PERK_RECOMMENDED.format(
        champion_id=champion_id, position=position, map_id=map_id
    )


def session(champion_id=96, position="bottom", spell1=4, spell2=14):
    return {
        "localPlayerCellId": 0,
        "myTeam": [
            {
                "cellId": 0,
                "championId": champion_id,
                "assignedPosition": position,
                "spell1Id": spell1,
                "spell2Id": spell2,
            }
        ],
    }


def build(config=None, responses=None, failures=None, source=None, now=None):
    base = {
        endpoints.CHAMPION_SUMMARY: SUMMARY,
        endpoints.GAMEFLOW_SESSION: {"map": {"id": 11}},
        endpoints.PERK_PAGES: [USER_PAGE],
        endpoints.PERK_INVENTORY: {"canAddCustomPage": True},
        recommended_path(): [RECOMMENDATION],
    }
    base.update(responses or {})
    client = FakeLcuClient(
        base, posts={endpoints.PERK_PAGES: {"id": 77}}, failures=failures
    )
    catalog = ChampionCatalog(client)
    catalog.load()
    messages: list[str] = []
    config = config or Config(auto_spells=True, auto_runes=True)
    loadout = Loadout(
        client,
        config,
        catalog,
        log=messages.append,
        source=source,
        now=now or (lambda: 0.0),
    )
    return loadout, client, messages


# ---------- o lado do Flash ----------


def test_it_keeps_flash_on_the_key_the_player_already_uses():
    """Recomendação [21, 4] com Flash no D vira [4, 21]."""
    assert align_spells([21, 4], (4, 14)) == (4, 21)


def test_it_leaves_the_pair_alone_when_flash_already_matches():
    assert align_spells([4, 14], (4, 12)) == (4, 14)


def test_it_has_nothing_to_align_when_no_spell_is_shared():
    assert align_spells([4, 12], (7, 21)) == (4, 12)


def test_it_aligns_by_whichever_spell_is_shared():
    """Golpear vale o mesmo raciocínio do Flash para quem joga selva."""
    assert align_spells([11, 4], (4, 11)) == (4, 11)


def test_it_survives_a_player_with_no_spells_yet():
    assert align_spells([21, 4], (None, None)) == (21, 4)


# ---------- feitiços ----------


def test_it_sends_the_recommended_spells_to_the_client():
    loadout, client, _ = build(Config(auto_spells=True))

    loadout.apply(session())

    assert (
        endpoints.CHAMP_SELECT_MY_SELECTION,
        {"spell1Id": 4, "spell2Id": 21},
    ) in client.payloads


def test_it_leaves_the_spells_alone_when_the_switch_is_off():
    loadout, client, _ = build(Config(auto_spells=False, auto_runes=False))

    loadout.apply(session())

    assert client.paths("PATCH") == []


def test_it_does_not_touch_spells_that_are_already_right():
    """Sem isto o app mandaria um PATCH por partida sem mudar nada."""
    loadout, client, _ = build(Config(auto_spells=True))

    loadout.apply(session(spell1=4, spell2=21))

    assert client.paths("PATCH") == []


# ---------- runas ----------


def test_it_creates_the_page_from_the_recommendation():
    loadout, client, _ = build(Config(auto_runes=True))

    loadout.apply(session())

    _, body = next(p for p in client.payloads if p[0] == endpoints.PERK_PAGES)
    assert body["primaryStyleId"] == 8000
    assert body["subStyleId"] == 8400
    assert body["selectedPerkIds"] == PERK_IDS
    assert body["name"].startswith(PAGE_PREFIX)


def test_it_makes_the_new_page_the_current_one():
    """Criar a página não a ativa: sem isto o jogador entraria com a antiga."""
    loadout, client, _ = build(Config(auto_runes=True))

    loadout.apply(session())

    assert (endpoints.PERK_CURRENT_PAGE, 77) in client.payloads


def test_it_replaces_only_the_page_it_created_before():
    loadout, client, _ = build(
        Config(auto_runes=True), responses={endpoints.PERK_PAGES: [USER_PAGE, MY_PAGE]}
    )

    loadout.apply(session())

    assert client.paths("DELETE") == [endpoints.PERK_PAGE.format(page_id=1)]


def test_it_never_deletes_a_page_the_user_made():
    loadout, client, _ = build(
        Config(auto_runes=True), responses={endpoints.PERK_PAGES: [USER_PAGE]}
    )

    loadout.apply(session())

    assert client.paths("DELETE") == []


def test_it_gives_up_instead_of_making_room_by_force():
    """Sem espaço, o app avisa — apagar runa alheia não é opção."""
    loadout, client, messages = build(
        Config(auto_runes=True),
        responses={endpoints.PERK_INVENTORY: {"canAddCustomPage": False}},
    )

    loadout.apply(session())

    assert client.paths("POST") == []
    assert any("espaço" in message for message in messages)


# ---------- quando agir ----------


def test_it_waits_until_a_champion_is_locked():
    """Durante o hover o campeão ainda pode mudar; nada a fazer ainda."""
    loadout, client, _ = build()
    before = len(client.calls)

    loadout.apply(session(champion_id=0))

    assert len(client.calls) == before


def test_it_acts_once_per_champion():
    loadout, client, _ = build()

    loadout.apply(session())
    before = len(client.calls)
    loadout.apply(session())

    assert len(client.calls) == before


def test_it_acts_again_when_the_champion_changes():
    """Troca depois do lock acontece: o equipamento tem que acompanhar."""
    loadout, client, _ = build(
        responses={recommended_path(champion_id=64): [RECOMMENDATION]}
    )

    loadout.apply(session())
    loadout.apply(session(champion_id=64))

    assert recommended_path(champion_id=64) in client.paths("GET")


def test_reset_lets_the_next_match_start_over():
    loadout, client, _ = build()

    loadout.apply(session())
    loadout.reset()
    loadout.apply(session())

    assert client.paths("GET").count(recommended_path()) == 2


# ---------- rota e mapa ----------


def test_it_asks_for_the_lane_the_client_assigned():
    loadout, client, _ = build(
        responses={recommended_path(position="UTILITY"): [RECOMMENDATION]}
    )

    loadout.apply(session(position="utility"))

    assert recommended_path(position="UTILITY") in client.paths("GET")


def test_blind_pick_asks_for_the_champion_default_lane():
    """Sem rota atribuída a Riot responde pela rota natural do campeão."""
    loadout, client, _ = build(
        responses={recommended_path(position="NONE"): [RECOMMENDATION]}
    )

    loadout.apply(session(position=""))

    assert recommended_path(position="NONE") in client.paths("GET")


def test_aram_asks_for_its_own_map():
    """No mapa 12 a recomendação troca os feitiços — Fantasma entra."""
    loadout, client, _ = build(
        responses={
            endpoints.GAMEFLOW_SESSION: {"map": {"id": 12}},
            recommended_path(map_id=12): [RECOMMENDATION],
        }
    )

    loadout.apply(session())

    assert recommended_path(map_id=12) in client.paths("GET")


# ---------- falhas ----------


def test_a_failure_does_not_reach_the_pick_and_ban():
    """Runa é conforto; escolher e banir é o motivo do app existir."""
    loadout, _, messages = build(failures={recommended_path()})

    loadout.apply(session())

    assert any("runas" in message for message in messages)


def test_it_does_not_retry_a_failure_every_tick():
    loadout, client, _ = build(failures={recommended_path()})

    loadout.apply(session())
    before = len(client.calls)
    loadout.apply(session())

    assert len(client.calls) == before


# ---------- a segunda opinião do OP.GG ----------


class SlowSource:
    """Fonte que só responde quando o teste mandar.

    A busca de verdade leva de três a seis segundos e roda fora da
    thread da seleção; segurar a resposta na mão é o que permite olhar
    o app no meio dessa espera.
    """

    def __init__(self, build=None, boom=False):
        self.build = build
        self.boom = boom
        self.gate = threading.Event()
        self.gate.set()
        self.calls = []

    def fetch(self, champion, position, aram):
        self.calls.append((champion, position, aram))
        self.gate.wait(timeout=5)
        if self.boom:
            raise RuntimeError("fonte quebrada")
        return self.build


OPGG_BUILD = OpggBuild(
    style=8100,
    sub_style=8200,
    perks=(8112, 8126, 8140, 8105, 8224, 8233, 5008, 5008, 5001),
    spells=(4, 14),
)


def page_body(client):
    """Corpo do POST que criou a página de runas."""
    return next(p for p in client.payloads if p[0] == endpoints.PERK_PAGES)[1]


def settle(loadout, session_data, tries=50):
    """Aplica em ticks, como a janela faz, até a busca terminar."""
    for _ in range(tries):
        loadout.apply(session_data)
        if loadout._pending is None:
            return
        time.sleep(0.01)


def test_the_opgg_page_is_the_one_that_gets_created():
    loadout, client, _ = build(source=SlowSource(OPGG_BUILD))

    settle(loadout, session())

    created = page_body(client)
    assert created["selectedPerkIds"] == list(OPGG_BUILD.perks)
    assert created["primaryStyleId"] == 8100


def test_the_opgg_spells_still_respect_the_flash_key():
    """A regra do Flash vale para qualquer fonte, não só para a Riot."""
    loadout, client, _ = build(source=SlowSource(OPGG_BUILD))

    settle(loadout, session(spell1=14, spell2=4))

    assert endpoints.CHAMP_SELECT_MY_SELECTION not in client.paths("PATCH")


def test_it_asks_the_opgg_about_the_champion_and_the_lane():
    """Pelo alias, não pelo nome que o cliente mostra.

    Num cliente em português o nome vem traduzido, e o OP.GG não
    conhece "Nunu e Willump". O alias é o mesmo em qualquer idioma.
    """
    source = SlowSource(OPGG_BUILD)
    loadout, _, _ = build(source=source)

    settle(loadout, session())

    assert source.calls == [("KogMaw", "bottom", False)]


def test_the_abyss_is_announced_to_the_opgg():
    source = SlowSource(OPGG_BUILD)
    loadout, _, _ = build(
        source=source,
        responses={
            endpoints.GAMEFLOW_SESSION: {"map": {"id": 12}},
            recommended_path(map_id=12): [RECOMMENDATION],
        },
    )

    settle(loadout, session())

    assert source.calls[0][2] is True


def test_nothing_is_applied_while_the_answer_has_not_arrived():
    """O tick não pode travar esperando a rede: a seleção corre junto."""
    source = SlowSource(OPGG_BUILD)
    source.gate.clear()
    loadout, client, _ = build(source=source)

    loadout.apply(session())

    assert client.paths("POST") == []
    source.gate.set()


def test_the_answer_is_applied_on_a_later_tick():
    source = SlowSource(OPGG_BUILD)
    source.gate.clear()
    loadout, client, _ = build(source=source)

    loadout.apply(session())
    source.gate.set()
    settle(loadout, session())

    assert endpoints.PERK_PAGES in client.paths("POST")


def test_a_slow_opgg_gives_way_to_the_riot():
    """Seis segundos é o teto: depois disso a seleção já anda sozinha."""
    clock = [0.0]
    source = SlowSource(OPGG_BUILD)
    source.gate.clear()
    loadout, client, _ = build(source=source, now=lambda: clock[0])

    loadout.apply(session())
    clock[0] = 99.0
    loadout.apply(session())
    source.gate.set()

    created = page_body(client)
    assert created["selectedPerkIds"] == PERK_IDS


def test_an_empty_answer_gives_way_to_the_riot():
    loadout, client, _ = build(source=SlowSource(None))

    settle(loadout, session())

    created = page_body(client)
    assert created["selectedPerkIds"] == PERK_IDS


def test_a_broken_source_gives_way_to_the_riot():
    """Exceção na fonte é problema dela; a seleção segue equipada."""
    loadout, client, _ = build(source=SlowSource(boom=True))

    settle(loadout, session())

    created = page_body(client)
    assert created["selectedPerkIds"] == PERK_IDS


def test_the_opgg_is_asked_once_per_champion():
    source = SlowSource(OPGG_BUILD)
    loadout, _, _ = build(source=source)

    settle(loadout, session())
    loadout.apply(session())

    assert len(source.calls) == 1


def test_a_new_champ_select_starts_over():
    source = SlowSource(OPGG_BUILD)
    loadout, _, _ = build(source=source)

    settle(loadout, session())
    loadout.reset()
    settle(loadout, session())

    assert len(source.calls) == 2


def test_a_client_hiccup_before_the_search_does_not_reach_the_tick():
    """Descobrir o mapa é o primeiro passo da busca externa, e
    ele fala com o cliente. Se essa pergunta falhar, a exceção não
    pode subir: quem chama `apply` é o mesmo tick que escolhe e
    bane campeão, e ele roda logo depois.
    """
    loadout, _, _ = build(
        source=SlowSource(OPGG_BUILD),
        failures={endpoints.GAMEFLOW_SESSION},
    )

    settle(loadout, session())  # não levanta


def test_a_disconnect_during_the_search_does_not_reach_the_tick():
    loadout, client, _ = build(source=SlowSource(OPGG_BUILD))
    client.closed = True

    loadout.apply(session())  # não levanta


def test_the_journal_says_the_runes_came_from_the_opgg():
    """Saber a origem é metade do valor: sem isso não dá para
    perceber que o OP.GG parou de responder.
    """
    loadout, _, messages = build(source=SlowSource(OPGG_BUILD))

    settle(loadout, session())

    assert any("OP.GG" in message for message in messages)


def test_the_journal_says_when_the_riot_answered_instead():
    loadout, _, messages = build(source=SlowSource(None))

    settle(loadout, session())

    assert any("Riot" in message for message in messages)
