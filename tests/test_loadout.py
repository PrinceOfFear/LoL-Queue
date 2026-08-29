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

import pytest

from lolqueue.config import Config
from lolqueue.core.champions import ChampionCatalog
from lolqueue.core.loadout import (
    PAGE_PREFIX,
    WAIT_SECONDS,
    Loadout,
    align_spells,
)
from lolqueue.core.opgg import Block, Build as OpggBuild, Page
from lolqueue.lcu import endpoints
from lolqueue.lcu.client import ClientClosed
from tests.fakes import FakeLcuClient

SUMMARY = [{"id": 96, "name": "Kog Maw", "alias": "KogMaw"}]

PERK_IDS = [8008, 9111, 9103, 8299, 8429, 8451, 5005, 5008, 5001]

RECOMMENDATION = {
    "primaryPerkStyleId": 8000,
    "secondaryPerkStyleId": 8400,
    "summonerSpellIds": [21, 4],
    "perks": [{"id": perk} for perk in PERK_IDS],
}

ITEM_SETS = endpoints.ITEM_SETS.format(summoner_id=42)

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


def build(
    config=None,
    responses=None,
    failures=None,
    source=None,
    now=None,
    on_options=None,
):
    base = {
        endpoints.CHAMPION_SUMMARY: SUMMARY,
        endpoints.CURRENT_SUMMONER: {"summonerId": 42},
        ITEM_SETS: {"accountId": 7, "itemSets": [], "timestamp": 0},
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
        on_rune_options=on_options,
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


def test_the_chosen_key_wins_over_what_is_on_screen():
    """Conta emprestada: o Flash vai onde o jogador pediu, não onde estava."""
    assert align_spells([21, 4], (4, 14), "f") == (21, 4)
    assert align_spells([4, 14], (14, 4), "d") == (4, 14)


def test_the_chosen_key_moves_flash_even_with_no_spells_yet():
    assert align_spells([21, 4], (None, None), "d") == (4, 21)


def test_a_recommendation_without_flash_still_follows_the_screen():
    """Sem Flash na dupla não há tecla a respeitar — vale o alinhamento."""
    assert align_spells([21, 14], (14, 12), "d") == (14, 21)


def test_the_default_key_leaves_the_old_behaviour_alone():
    assert align_spells([21, 4], (4, 14), "auto") == (4, 21)


# ---------- feitiços ----------


def test_it_sends_the_recommended_spells_to_the_client():
    loadout, client, _ = build(Config(auto_spells=True))

    loadout.apply(session())

    assert (
        endpoints.CHAMP_SELECT_MY_SELECTION,
        {"spell1Id": 4, "spell2Id": 21},
    ) in client.payloads


def test_the_key_from_the_settings_reaches_the_client():
    """A escolha da tela precisa chegar ao PATCH, não parar na config."""
    loadout, client, _ = build(Config(auto_spells=True, flash_key="f"))

    loadout.apply(session(spell1=4, spell2=14))

    assert (
        endpoints.CHAMP_SELECT_MY_SELECTION,
        {"spell1Id": 21, "spell2Id": 4},
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
    """Sem vaga de verdade, o app avisa — apagar runa alheia é proibido.

    "De verdade" é o cliente recusando a criação, não a bandeira do
    inventário dizendo que não dá: quem manda aqui é a resposta ao POST.
    """
    loadout, client, messages = build(
        Config(auto_runes=True),
        responses={endpoints.PERK_INVENTORY: {"canAddCustomPage": False}},
        failures={("POST", endpoints.PERK_PAGES)},
    )

    loadout.apply(session())

    assert client.paths("DELETE") == []
    assert any("espaço" in message for message in messages)


def test_a_client_that_lies_about_being_full_does_not_cost_the_runes():
    """A bandeira diz que não cabe; o POST prova que cabia.

    Aconteceu numa seleção inteira: `canAddCustomPage` falso com uma
    página nossa parada ali, e o app entrando em partida sem runa
    enquanto repetia no diário que a culpa era do jogador. A bandeira
    agora só decide se vale abrir espaço antes — criar, ele tenta
    sempre.
    """
    loadout, client, messages = build(
        Config(auto_runes=True),
        responses={
            endpoints.PERK_INVENTORY: {"canAddCustomPage": False},
            endpoints.PERK_PAGES: [MY_PAGE, USER_PAGE],
        },
    )

    loadout.apply(session())

    assert endpoints.PERK_PAGES in client.paths("POST")
    assert any("Runas" in message for message in messages)
    assert not any("espaço" in message for message in messages)


def test_the_same_complaint_is_not_repeated_every_tick():
    """Uma seleção dura minutos; a mesma queixa não pode encher o diário.

    O log real trouxe onze linhas idênticas em noventa segundos, e o
    que ficou de fora foram justamente as linhas que explicavam o
    resto da seleção.
    """
    loadout, client, messages = build(
        Config(auto_runes=True),
        responses={endpoints.PERK_INVENTORY: {"canAddCustomPage": False}},
        failures={("POST", endpoints.PERK_PAGES)},
    )

    for _ in range(5):
        loadout.apply(session())

    assert len([m for m in messages if "espaço" in m]) == 1


def test_a_new_selection_hears_the_complaint_again():
    """Calar para sempre seria a falha calada de novo, só que mais tarde."""
    loadout, client, messages = build(
        Config(auto_runes=True),
        responses={endpoints.PERK_INVENTORY: {"canAddCustomPage": False}},
        failures={("POST", endpoints.PERK_PAGES)},
    )

    loadout.apply(session())
    loadout.reset()
    loadout.apply(session())

    assert len([m for m in messages if "espaço" in m]) == 2


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
        # Guardado à parte, sem entrar em `calls`: mudar a assinatura
        # de `fetch` não pode desmanchar as asserções que já comparam
        # `calls` com uma tupla exata.
        self.tiers = []

    def fetch(self, champion, position, aram, tier=None):
        self.calls.append((champion, position, aram))
        self.tiers.append(tier)
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


COM_ARSENAL = OpggBuild(
    style=8100,
    sub_style=8200,
    perks=(8112, 8126, 8140, 8105, 8224, 8233, 5008, 5008, 5001),
    spells=(4, 14),
    pages=(
        Page(
            label="",
            blocks=(
                Block(label="Iniciais", items=(1055, 2003), win_rate=0.5),
                Block(label="Principais", items=(3031, 3094), win_rate=0.53),
            ),
        ),
    ),
)

COM_VARIAS_PAGINAS = OpggBuild(
    style=8100,
    sub_style=8200,
    perks=(8112, 8126, 8140, 8105, 8224, 8233, 5008, 5008, 5001),
    spells=(4, 14),
    pages=(
        Page(
            label="Mais jogada",
            blocks=(Block(label="Situacionais", items=(3135,), win_rate=0.0),),
        ),
        Page(
            label="Maior taxa",
            blocks=(Block(label="Situacionais", items=(3157,), win_rate=0.0),),
        ),
    ),
)


def page_body(client):
    """Corpo do POST que criou a página de runas."""
    return next(p for p in client.payloads if p[0] == endpoints.PERK_PAGES)[1]


def quieto(loadout):
    """Nenhuma busca em voo — nem a principal, nem a das opções."""
    if loadout._pending is not None:
        return False
    thread = loadout._options_thread
    return thread is None or not thread.is_alive()


def settle(loadout, session_data, tries=200):
    """Aplica em ticks, como a janela faz, até a busca terminar.

    Espera também pelos elos de comparação: eles correm numa thread
    própria, que termina depois da principal.
    """
    for _ in range(tries):
        loadout.apply(session_data)
        if quieto(loadout):
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


def test_the_chosen_tier_travels_to_the_opgg():
    """O elo é dos ajustes, não um valor fixo dentro do módulo."""
    source = SlowSource(OPGG_BUILD)
    config = Config(auto_spells=True, auto_runes=True, opgg_tier="platinum_plus")
    loadout, _, _ = build(config=config, source=source)

    settle(loadout, session())

    assert source.tiers == ["platinum_plus"]


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


def test_a_closed_client_is_the_watchers_business_not_a_rune_error():
    """Cliente fechado é a única falha que sobe daqui.

    “Não atrapalhar o pick e o ban” não quer dizer nada quando não há
    mais cliente para escolher nem banir. Quem espera por esta exceção é
    o watcher, que reconecta; engolindo-a, o app trocava o “Cliente do
    LoL fechado.” por um erro de runa que não explica coisa alguma, e
    ainda esperava o próximo tick para descobrir o óbvio. É a mesma
    regra que o motor já segue nas chamadas dele.
    """
    loadout, client, messages = build(source=SlowSource(OPGG_BUILD))
    client.closed = True

    with pytest.raises(ClientClosed):
        loadout.apply(session())
    assert messages == []


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


# ---------- opções de runa por elo ----------
#
# O OP.GG devolve builds diferentes conforme o elo consultado, e é essa
# a única variedade honesta disponível aqui. O elo dos Ajustes continua
# mandando no que é aplicado sozinho; os elos de comparação só abastecem
# os botões da tela.


class TieredSource:
    """Fonte que responde uma build por elo, como o OP.GG faz.

    Elo fora do mapa devolve `None` — é assim que o OP.GG trata campeão
    sem amostra naquela faixa.
    """

    def __init__(self, builds, boom=()):
        self.builds = dict(builds)
        self.boom = set(boom)
        self.tiers = []

    def fetch(self, champion, position, aram, tier=None):
        self.tiers.append(tier)
        if tier in self.boom:
            raise RuntimeError("fonte quebrada")
        return self.builds.get(tier)


def rune_build(first_perk):
    """Uma build de runa reconhecível pelo primeiro id."""
    return OpggBuild(
        style=8100,
        sub_style=8200,
        perks=(first_perk, 8126, 8140, 8105, 8224, 8233, 5008, 5008, 5001),
        spells=(4, 14),
    )


DIAMANTE = rune_build(8112)
MESTRE = rune_build(8124)
DESAFIANTE = rune_build(8128)

TRES_ELOS = {
    "diamond_plus": DIAMANTE,
    "master": MESTRE,
    "challenger": DESAFIANTE,
}


def com_opcoes(**extra):
    return Config(auto_runes=True, auto_runes_options=True, **extra)


def pages_created(client):
    """Corpos dos POST que criaram páginas de runa, na ordem."""
    return [b for p, b in client.payloads if p == endpoints.PERK_PAGES]


def test_without_the_option_only_the_configured_tier_is_asked():
    """Desligada, a feature não custa nem uma consulta a mais."""
    source = TieredSource(TRES_ELOS)
    published = []
    loadout, _, _ = build(
        config=Config(auto_runes=True),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )

    settle(loadout, session())

    assert source.tiers == ["diamond_plus"]
    assert published == []


def test_the_comparison_tiers_are_offered_when_the_option_is_on():
    source = TieredSource(TRES_ELOS)
    published = []
    loadout, _, _ = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )

    settle(loadout, session())

    # O elo dos Ajustes já foi consultado para o build automático; não é
    # perguntado de novo só por também ser um dos de comparação.
    assert source.tiers == ["diamond_plus", "master", "challenger"]
    assert published[-1] == (["diamond_plus", "master", "challenger"], "diamond_plus")


def test_the_screen_gets_the_builds_not_just_the_tier_names():
    """A tela desenha a árvore de cada elo, então precisa das runas de
    cada um — só o nome do elo não dá para desenhar nada."""
    source = TieredSource(TRES_ELOS)
    published = []
    loadout, _, _ = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append(builds),
    )

    settle(loadout, session())

    builds = published[-1]
    assert sorted(builds) == ["challenger", "diamond_plus", "master"]
    assert builds["master"].perks == TRES_ELOS["master"].perks


def test_the_published_builds_do_not_change_under_the_screen():
    """A tela lê no seu tempo; a thread das opções troca o dicionário
    inteiro. Sem uma cópia, uma seleção nova mexeria no que a tela ainda
    está desenhando."""
    source = TieredSource(TRES_ELOS)
    published = []
    loadout, _, _ = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append(builds),
    )

    settle(loadout, session())
    entregue = published[-1]
    loadout.reset()

    assert sorted(entregue) == ["challenger", "diamond_plus", "master"]


def test_the_comparison_tiers_do_not_follow_the_settings_tier():
    """O elo dos Ajustes manda no que é aplicado, não no leque."""
    source = TieredSource(TRES_ELOS)
    loadout, _, _ = build(config=com_opcoes(opgg_tier="gold"), source=source)

    settle(loadout, session())

    assert source.tiers == ["gold", "diamond_plus", "master", "challenger"]


def test_two_tiers_with_the_same_page_become_one_option():
    """Dois botões idênticos lado a lado só ocupariam espaço."""
    source = TieredSource({**TRES_ELOS, "master": DIAMANTE})
    published = []
    loadout, _, _ = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )

    settle(loadout, session())

    assert published[-1][0] == ["diamond_plus", "challenger"]


def test_a_tier_that_does_not_answer_is_not_offered():
    """Vaga vazia fica vazia: repetir outra build seria inventar dado."""
    source = TieredSource({"diamond_plus": DIAMANTE, "challenger": DESAFIANTE})
    published = []
    loadout, _, _ = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )

    settle(loadout, session())

    assert published[-1][0] == ["diamond_plus", "challenger"]


def test_a_tier_that_breaks_does_not_take_the_others_down():
    source = TieredSource(TRES_ELOS, boom={"master"})
    published = []
    loadout, client, _ = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )

    settle(loadout, session())

    assert published[-1][0] == ["diamond_plus", "challenger"]
    assert pages_created(client)[0]["selectedPerkIds"] == list(DIAMANTE.perks)


def test_the_automatic_page_is_still_the_settings_tier():
    """A tela oferece; quem entra em partida sem clicar em nada não fica
    sem runa nem com a de outro elo."""
    source = TieredSource(TRES_ELOS)
    loadout, client, _ = build(
        config=com_opcoes(opgg_tier="challenger"), source=source
    )

    settle(loadout, session())

    assert pages_created(client) == [
        {
            "name": PAGE_PREFIX + ": Kog Maw",
            "primaryStyleId": 8100,
            "subStyleId": 8200,
            "selectedPerkIds": list(DESAFIANTE.perks),
        }
    ]


def test_choosing_another_tier_swaps_the_page_in_the_client():
    source = TieredSource(TRES_ELOS)
    loadout, client, _ = build(config=com_opcoes(), source=source)
    settle(loadout, session())

    loadout.request_rune_option("challenger")
    loadout.apply(session())

    assert pages_created(client)[-1]["selectedPerkIds"] == list(DESAFIANTE.perks)
    assert client.payloads[-1] == (endpoints.PERK_CURRENT_PAGE, 77)


def test_the_swap_reuses_the_single_page_the_app_keeps():
    """Trocar de opção não pode ir enchendo o cliente de páginas nossas."""
    source = TieredSource(TRES_ELOS)
    loadout, client, _ = build(
        config=com_opcoes(),
        source=source,
        responses={endpoints.PERK_PAGES: [USER_PAGE, MY_PAGE]},
    )
    settle(loadout, session())

    loadout.request_rune_option("master")
    loadout.apply(session())

    assert client.paths("DELETE") == [endpoints.PERK_PAGE.format(page_id=1)] * 2


def test_the_swap_is_written_down_and_the_tela_hears_about_it():
    source = TieredSource(TRES_ELOS)
    published = []
    loadout, _, messages = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )
    settle(loadout, session())

    loadout.request_rune_option("master")
    loadout.apply(session())

    assert any("Mestre" in message for message in messages)
    assert published[-1][1] == "master"


def test_the_click_only_touches_the_client_on_the_next_tick():
    """O clique chega pela thread da GUI e só deixa um bilhete."""
    source = TieredSource(TRES_ELOS)
    loadout, client, _ = build(config=com_opcoes(), source=source)
    settle(loadout, session())
    before = len(client.calls)

    loadout.request_rune_option("master")

    assert len(client.calls) == before


def test_a_tier_that_was_not_offered_is_ignored():
    source = TieredSource({"diamond_plus": DIAMANTE})
    loadout, client, _ = build(config=com_opcoes(), source=source)
    settle(loadout, session())
    before = len(client.calls)

    loadout.request_rune_option("master")
    loadout.apply(session())

    assert len(client.calls) == before


def test_a_new_champ_select_takes_the_options_off_the_screen():
    source = TieredSource(TRES_ELOS)
    published = []
    loadout, _, _ = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )
    settle(loadout, session())

    loadout.reset()

    assert published[-1] == ([], None)


def test_the_riot_fallback_offers_nothing():
    """Sem resposta do OP.GG não há opção nenhuma para oferecer."""
    published = []
    loadout, client, _ = build(
        config=com_opcoes(),
        source=TieredSource({}),
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )

    settle(loadout, session())

    assert published == []
    assert pages_created(client)[0]["selectedPerkIds"] == PERK_IDS


class GatedTierSource:
    """Fonte em que só os elos de comparação demoram.

    Medido contra o OP.GG de verdade, as três consultas somam de dez a
    quatorze segundos, e o teto de espera do equipamento é oito. É esse
    descompasso que os testes abaixo reproduzem sem esperar de verdade.
    """

    def __init__(self, builds, settings_tier="diamond_plus"):
        self.builds = dict(builds)
        self.settings_tier = settings_tier
        self.gate = threading.Event()
        self.tiers = []

    def fetch(self, champion, position, aram, tier=None):
        self.tiers.append(tier)
        if tier != self.settings_tier:
            self.gate.wait(timeout=5)
        return self.builds.get(tier)


def test_the_comparison_tiers_do_not_spend_the_waiting_budget():
    """O teto de oito segundos é da build principal, e só dela.

    Somadas, as consultas dos elos de comparação passam do teto. Se
    corressem no mesmo orçamento, ligar as opções jogaria as runas e o
    arsenal na reserva da Riot em toda seleção — justamente as duas
    coisas que já funcionavam.
    """
    source = GatedTierSource(TRES_ELOS)
    relogio = [0.0]
    loadout, client, messages = build(
        config=com_opcoes(), source=source, now=lambda: relogio[0]
    )
    dados = session()

    loadout.apply(dados)
    loadout._pending.thread.join(timeout=5)
    # Os elos de comparação ainda estão presos no portão; o tempo passa
    # do teto e a build principal já está em mãos há muito.
    relogio[0] = WAIT_SECONDS + 1
    loadout.apply(dados)
    source.gate.set()

    assert pages_created(client)[0]["selectedPerkIds"] == list(DIAMANTE.perks)
    assert not any("demorou" in message for message in messages)


def test_a_slow_comparison_tier_does_not_hold_up_the_arsenal():
    """Mesma raiz do teste acima, pelo lado da loja."""
    source = GatedTierSource({**TRES_ELOS, "diamond_plus": COM_ARSENAL})
    relogio = [0.0]
    loadout, client, _ = build(
        config=com_opcoes(auto_items=True), source=source, now=lambda: relogio[0]
    )
    dados = session()

    loadout.apply(dados)
    loadout._pending.thread.join(timeout=5)
    relogio[0] = WAIT_SECONDS + 1
    loadout.apply(dados)
    source.gate.set()

    assert ITEM_SETS in client.paths("PUT")


def test_the_options_still_reach_the_screen_after_the_budget_is_gone():
    """Chegando tarde, elas ainda valem: a seleção dura minutos."""
    source = GatedTierSource(TRES_ELOS)
    relogio = [0.0]
    published = []
    loadout, _, _ = build(
        config=com_opcoes(),
        source=source,
        now=lambda: relogio[0],
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )
    dados = session()

    loadout.apply(dados)
    loadout._pending.thread.join(timeout=5)
    relogio[0] = WAIT_SECONDS + 1
    loadout.apply(dados)
    source.gate.set()
    settle(loadout, dados)

    assert published[-1] == (["diamond_plus", "master", "challenger"], "diamond_plus")


def test_the_options_show_up_even_when_nothing_could_be_applied():
    """Elo dos Ajustes sem amostra e Riot calada: é a hora em que
    escolher à mão vale mais, e era justo quando a tela ficava vazia."""
    published = []
    loadout, _, _ = build(
        config=com_opcoes(opgg_tier="gold"),
        source=TieredSource({"master": MESTRE, "challenger": DESAFIANTE}),
        responses={recommended_path(): []},
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )

    settle(loadout, session())

    assert published[-1] == (["master", "challenger"], None)


def test_a_page_of_the_user_that_starts_like_ours_is_left_alone():
    """“LoL Queue Ranqueada”, feita à mão, não é nossa: o nome que o app
    reconhece é o dele inteiro, com os dois pontos."""
    quase = {"id": 3, "name": PAGE_PREFIX + " Ranqueada", "isDeletable": True}
    loadout, client, _ = build(
        responses={endpoints.PERK_PAGES: [USER_PAGE, quase]}
    )

    loadout.apply(session())

    assert endpoints.PERK_PAGE.format(page_id=3) not in client.paths("DELETE")


def test_a_failed_swap_leaves_the_player_with_a_page():
    """Apagar antes de ter substituta é como o jogador entrava na
    partida sem runa nenhuma quando o cliente recusava o POST."""
    source = TieredSource(TRES_ELOS)
    loadout, client, _ = build(
        config=com_opcoes(),
        source=source,
        responses={endpoints.PERK_PAGES: [USER_PAGE, MY_PAGE]},
    )
    settle(loadout, session())
    antes = len(client.paths("DELETE"))
    client.failures.add(("POST", endpoints.PERK_PAGES))

    loadout.request_rune_option("master")
    loadout.apply(session())

    assert len(client.paths("DELETE")) == antes


def test_a_failed_swap_leaves_the_screen_telling_the_truth():
    """Recusado o POST, nada mudou no cliente: a página de antes segue
    ativa, e é ela que a tela tem que continuar marcando."""
    source = TieredSource(TRES_ELOS)
    published = []
    loadout, client, messages = build(
        config=com_opcoes(),
        source=source,
        on_options=lambda tiers, active, builds: published.append((tiers, active)),
    )
    settle(loadout, session())
    client.failures.add(("POST", endpoints.PERK_PAGES))

    loadout.request_rune_option("master")
    loadout.apply(session())

    assert published[-1][1] == "diamond_plus"
    assert any("recusou" in message for message in messages)


# ---------- o arsenal na loja ----------


def test_the_arsenal_reaches_the_shop():
    loadout, client, _ = build(
        config=Config(auto_runes=True, auto_items=True),
        source=SlowSource(COM_ARSENAL),
    )

    settle(loadout, session())

    gravado = next(b for p, b in client.payloads if p == ITEM_SETS)
    assert gravado["itemSets"][0]["title"] == "LoL Queue: Kog Maw"


def test_several_pages_become_several_sets_in_the_shop():
    """O pedido: mais de uma aba de arsenal, não um bloco por
    alternativa dentro de um conjunto só."""
    loadout, client, _ = build(
        config=Config(auto_items=True),
        source=SlowSource(COM_VARIAS_PAGINAS),
    )

    settle(loadout, session())

    gravado = next(b for p, b in client.payloads if p == ITEM_SETS)
    titulos = [s["title"] for s in gravado["itemSets"]]
    assert titulos == [
        "LoL Queue: Kog Maw — Mais jogada",
        "LoL Queue: Kog Maw — Maior taxa",
    ]


def test_without_the_option_the_shop_is_left_alone():
    """Quem não pediu arsenal não tem a loja mexida."""
    loadout, client, _ = build(
        config=Config(auto_runes=True, auto_items=False),
        source=SlowSource(COM_ARSENAL),
    )

    settle(loadout, session())

    assert ITEM_SETS not in client.paths("PUT")


def test_the_arsenal_alone_needs_no_rune_page():
    """As três opções são independentes uma da outra."""
    loadout, client, _ = build(
        config=Config(auto_items=True),
        source=SlowSource(COM_ARSENAL),
    )

    settle(loadout, session())

    assert ITEM_SETS in client.paths("PUT")
    assert endpoints.PERK_PAGES not in client.paths("POST")


def test_the_riot_fallback_brings_no_arsenal():
    """A recomendação da Riot não tem itens, e inventar um
    arsenal a partir do nada seria pior que não montar nenhum.
    """
    loadout, client, _ = build(
        config=Config(auto_runes=True, auto_items=True),
        source=SlowSource(None),
    )

    settle(loadout, session())

    assert ITEM_SETS not in client.paths("PUT")
    assert endpoints.PERK_PAGES in client.paths("POST")


def test_a_shop_failure_does_not_reach_the_tick():
    """O mesmo tick escolhe e bane campeão; nada aqui pode
    interromper aquilo.
    """
    loadout, _, messages = build(
        config=Config(auto_items=True),
        source=SlowSource(COM_ARSENAL),
        failures={ITEM_SETS},
    )

    settle(loadout, session())

    assert messages == [] or all(isinstance(m, str) for m in messages)


# ---------- o confronto no cliente ----------


class Guia:
    """O guia de confronto como o `Loadout` o enxerga: só a build."""

    def __init__(self, build=None):
        self.build = build


DO_CONFRONTO = OpggBuild(
    style=8000,
    sub_style=8300,
    perks=(8005, 9101, 9104, 8014, 8345, 8347, 5005, 5008, 5002),
    spells=(4, 7),
    pages=(
        Page(
            label="",
            blocks=(
                Block(label="Iniciais", items=(1055, 2003), win_rate=0.51),
                Block(label="Principais", items=(6672, 3094), win_rate=0.55),
            ),
        ),
    ),
)


def com_arsenal(**extra):
    """Um `Loadout` com o campeão já equipado e o arsenal na loja."""
    config = Config(auto_runes=True, auto_items=True, **extra)
    loadout, client, messages = build(config=config, source=SlowSource(COM_ARSENAL))
    settle(loadout, session())
    return loadout, client, messages


def titulos(client):
    caminho, corpo = next(
        (p, b) for p, b in reversed(client.payloads) if p == ITEM_SETS
    )
    return [item["title"] for item in corpo["itemSets"]]


def test_the_matchup_becomes_one_more_tab_in_the_shop():
    """A aba “vs Fulano”, do jeito que Blitz e Porofessor a põem lá."""
    loadout, client, _ = com_arsenal()

    loadout.request_matchup("Ezreal", Guia(DO_CONFRONTO))
    loadout.apply(session())

    assert titulos(client) == [
        "LoL Queue: Kog Maw",
        "LoL Queue: Kog Maw — vs Ezreal",
    ]


def test_the_champion_tab_survives_the_matchup_tab():
    """A loja só aceita a lista inteira: gravar uma apagaria a outra."""
    loadout, client, _ = com_arsenal()

    loadout.request_matchup("Ezreal", Guia(DO_CONFRONTO))
    loadout.apply(session())

    caminho, corpo = next(
        (p, b) for p, b in reversed(client.payloads) if p == ITEM_SETS
    )
    geral = corpo["itemSets"][0]
    assert [entry["id"] for entry in geral["blocks"][1]["items"]] == ["3031", "3094"]


def test_a_guide_with_nothing_to_say_installs_nothing():
    loadout, client, _ = com_arsenal()
    antes = len([p for p, _ in client.payloads if p == ITEM_SETS])

    loadout.request_matchup("Ezreal", Guia(None))
    loadout.apply(session())

    assert len([p for p, _ in client.payloads if p == ITEM_SETS]) == antes


def test_the_matchup_rune_becomes_one_more_option():
    vistos = []
    config = Config(auto_runes=True, auto_items=True, auto_runes_options=True)
    loadout, client, _ = build(
        config=config,
        source=SlowSource(COM_ARSENAL),
        on_options=lambda tiers, active, builds: vistos.append(tiers),
    )
    settle(loadout, session())

    loadout.request_matchup("Ezreal", Guia(DO_CONFRONTO))
    loadout.apply(session())

    assert "vs Ezreal" in vistos[-1]


def test_the_matchup_rune_waits_for_the_click():
    """Trocar a página ativa sozinho seria decidir pelo jogador."""
    config = Config(auto_runes=True, auto_items=True, auto_runes_options=True)
    loadout, client, _ = build(config=config, source=SlowSource(COM_ARSENAL))
    settle(loadout, session())
    antes = len(client.paths("POST"))

    loadout.request_matchup("Ezreal", Guia(DO_CONFRONTO))
    loadout.apply(session())

    assert len(client.paths("POST")) == antes


def test_clicking_the_matchup_option_installs_that_page():
    config = Config(auto_runes=True, auto_items=True, auto_runes_options=True)
    loadout, client, messages = build(config=config, source=SlowSource(COM_ARSENAL))
    settle(loadout, session())

    loadout.request_matchup("Ezreal", Guia(DO_CONFRONTO))
    loadout.apply(session())
    loadout.request_rune_option("vs Ezreal")
    loadout.apply(session())

    criada = [b for p, b in client.payloads if p == endpoints.PERK_PAGES][-1]
    assert criada["selectedPerkIds"] == list(DO_CONFRONTO.perks)
    assert any("confronto contra Ezreal" in linha for linha in messages)


def test_the_previous_opponent_leaves_the_list():
    """Um botão por confronto: o da rota de agora, não os de antes."""
    vistos = []
    config = Config(auto_runes=True, auto_items=True, auto_runes_options=True)
    loadout, client, _ = build(
        config=config,
        source=SlowSource(COM_ARSENAL),
        on_options=lambda tiers, active, builds: vistos.append(tiers),
    )
    settle(loadout, session())

    loadout.request_matchup("Ezreal", Guia(DO_CONFRONTO))
    loadout.apply(session())
    loadout.request_matchup("Jinx", Guia(DO_CONFRONTO))
    loadout.apply(session())

    assert vistos[-1].count("vs Jinx") == 1
    assert "vs Ezreal" not in vistos[-1]


def test_a_matchup_rune_equal_to_one_already_listed_does_not_repeat():
    """Dois botões com a mesma página só ocupariam espaço."""
    vistos = []
    config = Config(auto_runes=True, auto_items=True, auto_runes_options=True)
    loadout, client, _ = build(
        config=config,
        source=SlowSource(COM_ARSENAL),
        on_options=lambda tiers, active, builds: vistos.append(tiers),
    )
    settle(loadout, session())
    antes = list(vistos[-1])

    loadout.request_matchup("Ezreal", Guia(COM_ARSENAL))
    loadout.apply(session())

    assert vistos[-1] == antes
