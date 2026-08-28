# Histórico — placar nativo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refazer a linha de partida do "Histórico" para ficar igual à tela nativa do cliente do LoL (retrato+nível, itens, runas, gold) e permitir clicar numa partida para abrir, na mesma página, um placar completo (duas equipes, 10 jogadores, bans e objetivos) — também igual ao cliente. O histórico passa a se atualizar sozinho quando uma partida termina.

**Architecture:** `core/summoner_history.py` ganha os campos de build (itens/runas/feitiços/nível/gold) no `MatchSummary` já existente e três dataclasses novas (`ParticipantDetail`, `TeamDetail`, `GameDetail`) mais `fetch_game_detail`, seguindo exatamente o padrão tolerante a falha já usado por `_profile`/`_match_summaries`. Dois catálogos novos e enxutos (`ItemCatalog`, `SpellCatalog`, cópias reduzidas de `PerkCatalog`) resolvem id→ícone pelo cliente do LoL. `IconLoader` carrega os dois catálogos na mesma viagem que já carrega runas. Um `GameDetailLoader` novo (mesmo molde de `HistoryLoader`) busca o placar numa thread própria quando o usuário clica numa partida. `HistoryPage` ganha uma segunda visão (o placar) que substitui a lista no lugar, com um botão de voltar — mesmo mecanismo de mostrar/esconder que já separa `_content`/`_empty`. `MainWindow` liga tudo e passa a chamar `_refresh_history()` também quando a fase vira `EndOfGame`.

**Tech Stack:** Python, PySide6 (Qt widgets), pytest, servidor MCP do OP.GG (`mcp-api.op.gg`), LCU API local do cliente do LoL.

**Spec:** `docs/superpowers/specs/2026-08-23-historico-placar-nativo-design.md`

## Global Constraints

- Sem exceção vazando para quem chama: rede fora, campo faltando ou formato mudado sempre viram `None`/`()`, nunca uma exceção (regra já estabelecida no módulo).
- Nenhuma consulta nova de rede fora das já descritas — ícones de item/feitiço vêm do mesmo `AssetStore` genérico por URL já existente; nenhum cache novo.
- Só a aba "Placar" do cliente é replicada — nada de Visão Geral/Estatísticas/Gráficos/Runas nem `op_score_timeline`.
- Atualização automática usa o sinal de fase que o watcher já emite (`EndOfGame`) — nenhum polling novo por tempo.
- `IconLoader`/`HistoryLoader`/`MatchupLoader`/`GameDetailLoader` não têm teste unitário próprio (thin wrappers de `QThread`, mesmo padrão hoje) — a integração é verificada ao vivo no fim, com o cliente do LoL aberto.
- Ao final: fechar a instância do app já aberta, gerar o build novo, abrir, e comparar visualmente lista e placar com a tela equivalente do cliente do LoL (mesma conta Princee#adc usada nos testes).

---

## Task 1: `MatchSummary` ganha os campos de build

**Files:**
- Modify: `lolqueue/core/summoner_history.py`
- Test: `tests/test_summoner_history.py`
- Modify (helper only, para não quebrar a suíte): `tests/test_history_page.py`

**Interfaces:**
- Produces: `MatchSummary` com os campos novos `items: tuple[int, ...]`, `item_names: tuple[str, ...]`, `spells: tuple[int, int]`, `primary_style_id: int`, `primary_rune_id: int`, `secondary_style_id: int`, `champion_level: int`, `gold: int` (mantém todos os campos existentes, na mesma ordem, com os novos ao final).

- [ ] **Step 1: Escrever o teste com a resposta real (anonimizada) do `lol_list_summoner_matches`**

Em `tests/test_summoner_history.py`, substituir a constante `MATCHES` e o teste `test_matches_read_a_win_and_a_loss_with_kda_and_cs`:

```python
MATCHES = """class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,position,items,items_names,rune,spells,stats
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result

LolListSummonerMatches(Data([GameHistory("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,[Participant(54,"Malphite","TOP",[1056,3802,1001,1029,1026],["Anel de Doran","Capítulo Perdido","Botas","Couraça de Pano","Varinha Explosiva"],Rune(8200,8229,8400),[4,12],Stats(10,0,4,0,79,0,3901,"LOSE"))]),GameHistory("wgqT90Iiz72Bsm3unOefxkCMsMc-e8bCFWQ9MpHIUIo=","2026-08-23T16:56:57+09:00","SOLORANKED",1522,[Participant(22,"Ashe","ADC",[1086,3153,2003,3085,3123],["Arco de Doran","Espada do Rei Destruído","Poção de Vida","Furacão de Runaan","Chamado do Carrasco"],Rune(8000,8008,8300),[4,21],Stats(13,4,12,2,155,4,8902,"LOSE"))])]))"""


def test_matches_read_a_win_and_a_loss_with_kda_and_cs():
    source = SummonerHistorySource(send=FakeSend(matches_answer=MATCHES))

    matches = source.fetch_matches("Jogador", "BR1", "BR")

    assert matches == (
        MatchSummary(
            match_id="wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=",
            champion_id=54,
            champion_name="Malphite",
            result="LOSE",
            kills=0,
            deaths=4,
            assists=0,
            cs=79,
            duration_seconds=958,
            queue_type="SOLORANKED",
            position="TOP",
            played_at=datetime.fromisoformat("2026-08-23T17:18:49+09:00"),
            items=(1056, 3802, 1001, 1029, 1026),
            item_names=(
                "Anel de Doran",
                "Capítulo Perdido",
                "Botas",
                "Couraça de Pano",
                "Varinha Explosiva",
            ),
            spells=(4, 12),
            primary_style_id=8200,
            primary_rune_id=8229,
            secondary_style_id=8400,
            champion_level=10,
            gold=3901,
        ),
        MatchSummary(
            match_id="wgqT90Iiz72Bsm3unOefxkCMsMc-e8bCFWQ9MpHIUIo=",
            champion_id=22,
            champion_name="Ashe",
            result="LOSE",
            kills=4,
            deaths=12,
            assists=2,
            cs=159,
            duration_seconds=1522,
            queue_type="SOLORANKED",
            position="ADC",
            played_at=datetime.fromisoformat("2026-08-23T16:56:57+09:00"),
            items=(1086, 3153, 2003, 3085, 3123),
            item_names=(
                "Arco de Doran",
                "Espada do Rei Destruído",
                "Poção de Vida",
                "Furacão de Runaan",
                "Chamado do Carrasco",
            ),
            spells=(4, 21),
            primary_style_id=8000,
            primary_rune_id=8008,
            secondary_style_id=8300,
            champion_level=13,
            gold=8902,
        ),
    )


def test_items_come_in_whatever_length_the_match_really_has():
    """A grade da linha desenha o que a partida comprou — sem casas
    fixas para itens que nunca foram comprados."""
    answer = """class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,position,items,items_names,rune,spells,stats
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result

LolListSummonerMatches(Data([GameHistory("id1","2026-08-23T12:00:00+00:00","ARAM",600,[Participant(1,"Annie","MID",[1001,3020],["Botas","Sapatos Enfeitiçados"],Rune(8100,8112,8000),[4,14],Stats(6,2,3,1,40,0,2500,"WIN"))])]))"""
    source = SummonerHistorySource(send=FakeSend(matches_answer=answer))

    matches = source.fetch_matches("Jogador", "BR1", "BR")

    assert matches[0].items == (1001, 3020)
    assert matches[0].item_names == ("Botas", "Sapatos Enfeitiçados")
    assert matches[0].spells == (4, 14)


def test_a_match_missing_rune_data_is_discarded():
    """Sem runa não dá para desenhar a grade — a partida some da lista,
    não aparece pela metade. Mesma regra de tolerância do resto do
    parser."""
    answer = """class LolListSummonerMatches: data
class Data: game_history
class GameHistory: id,created_at,game_type,game_length_second,participants
class Participant: champion_id,champion_name,position,items,items_names,rune,spells,stats
class Rune: primary_page_id,primary_rune_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result

LolListSummonerMatches(Data([GameHistory("id1","2026-08-23T12:00:00+00:00","ARAM",600,[Participant(1,"Annie","MID",[1001],["Botas"],Rune(8100,8112),[4,14],Stats(6,2,3,1,40,0,2500,"WIN"))])]))"""
    source = SummonerHistorySource(send=FakeSend(matches_answer=answer))

    assert source.fetch_matches("Jogador", "BR1", "BR") == ()
```

- [ ] **Step 2: Rodar os testes e ver a falha**

Run: `py -m pytest tests/test_summoner_history.py -v`
Expected: FAIL — `TypeError: MatchSummary.__init__() got an unexpected keyword argument 'items'` (o dataclass ainda não tem os campos novos).

- [ ] **Step 3: Estender `MatchSummary`, `MATCH_FIELDS` e `_match_summaries`**

Em `lolqueue/core/summoner_history.py`, trocar `MATCH_FIELDS`:

```python
MATCH_FIELDS = (
    "data.game_history[].{id,created_at,game_length_second,game_type}",
    "data.game_history[].participants[].{champion_id,champion_name,position,items,items_names,spells}",
    "data.game_history[].participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}",
    "data.game_history[].participants[].stats.{champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,result}",
)
```

Trocar a dataclass `MatchSummary`:

```python
@dataclass(frozen=True)
class MatchSummary:
    """Uma partida, já filtrada pelo servidor para o jogador buscado."""

    match_id: str
    champion_id: int
    #: Em inglês, como o OP.GG manda. A UI troca pelo nome em
    #: português do catálogo já carregado, quando existir.
    champion_name: str
    result: str  # "WIN" | "LOSE"
    kills: int
    deaths: int
    assists: int
    cs: int
    duration_seconds: int
    queue_type: str
    position: str
    played_at: datetime
    items: tuple[int, ...]
    item_names: tuple[str, ...]
    spells: tuple[int, int]
    primary_style_id: int
    primary_rune_id: int
    secondary_style_id: int
    champion_level: int
    gold: int
```

Trocar `_match_summaries`:

```python
def _match_summaries(text: str, limit: int) -> tuple[MatchSummary, ...]:
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, MATCHES_ROOT)
    if data is None:
        return ()
    found: list[MatchSummary] = []
    for entry in mcp_format.entries(data.get("game_history", "")):
        game = mcp_format.unpack(entry, schema)
        if game is None:
            continue
        match_id = game.get("id", "").strip().strip('"')
        created_at = game.get("created_at", "").strip().strip('"')
        duration = mcp_format.to_int(game.get("game_length_second", ""))
        queue_type = game.get("game_type", "").strip().strip('"')
        participant = mcp_format.first(game.get("participants"))
        fields = mcp_format.unpack(participant, schema) if participant else None
        if fields is None or duration is None or not match_id or not created_at:
            continue
        champion_id = mcp_format.to_int(fields.get("champion_id", ""))
        champion_name = fields.get("champion_name", "").strip().strip('"')
        position = fields.get("position", "").strip().strip('"')
        items = mcp_format.to_ints(fields.get("items", "[]"))
        spells = mcp_format.to_ints(fields.get("spells", "[]"))
        rune = mcp_format.unpack(fields.get("rune"), schema)
        stats = mcp_format.unpack(fields.get("stats"), schema)
        if (
            champion_id is None
            or not champion_name
            or items is None
            or spells is None
            or len(spells) != 2
            or rune is None
            or stats is None
        ):
            continue
        primary_style_id = mcp_format.to_int(rune.get("primary_page_id", ""))
        primary_rune_id = mcp_format.to_int(rune.get("primary_rune_id", ""))
        secondary_style_id = mcp_format.to_int(rune.get("secondary_page_id", ""))
        champion_level = mcp_format.to_int(stats.get("champion_level", ""))
        kills = mcp_format.to_int(stats.get("kill", ""))
        deaths = mcp_format.to_int(stats.get("death", ""))
        assists = mcp_format.to_int(stats.get("assist", ""))
        minions = mcp_format.to_int(stats.get("minion_kill", "")) or 0
        neutral = mcp_format.to_int(stats.get("neutral_minion_kill", "")) or 0
        gold = mcp_format.to_int(stats.get("gold_earned", ""))
        result = stats.get("result", "").strip().strip('"')
        if (
            primary_style_id is None
            or primary_rune_id is None
            or secondary_style_id is None
            or champion_level is None
            or kills is None
            or deaths is None
            or assists is None
            or gold is None
            or not result
        ):
            continue
        try:
            played_at = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        found.append(
            MatchSummary(
                match_id=match_id,
                champion_id=champion_id,
                champion_name=champion_name,
                result=result,
                kills=kills,
                deaths=deaths,
                assists=assists,
                cs=minions + neutral,
                duration_seconds=duration,
                queue_type=queue_type,
                position=position,
                played_at=played_at,
                items=tuple(items),
                item_names=tuple(mcp_format.to_strings(fields.get("items_names", ""))),
                spells=(spells[0], spells[1]),
                primary_style_id=primary_style_id,
                primary_rune_id=primary_rune_id,
                secondary_style_id=secondary_style_id,
                champion_level=champion_level,
                gold=gold,
            )
        )
        if len(found) >= limit:
            break
    return tuple(found)
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `py -m pytest tests/test_summoner_history.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Atualizar o helper `match()` de `tests/test_history_page.py` para não quebrar essa suíte**

Em `tests/test_history_page.py`, trocar a função `match`:

```python
def match(**changes):
    base = dict(
        match_id="abc",
        champion_id=22,
        champion_name="Ashe",
        result="WIN",
        kills=6,
        deaths=6,
        assists=12,
        cs=188,
        duration_seconds=1686,
        queue_type="SOLORANKED",
        position="ADC",
        played_at=datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc),
        items=(1001, 1002),
        item_names=("Botas", "Espada Longa"),
        spells=(4, 12),
        primary_style_id=8200,
        primary_rune_id=8229,
        secondary_style_id=8400,
        champion_level=15,
        gold=8902,
    )
    base.update(changes)
    return MatchSummary(**base)
```

- [ ] **Step 6: Rodar a suíte inteira e confirmar que nada mais quebrou**

Run: `py -m pytest -q`
Expected: PASS em todos os testes (o que hoje é `HistoryPage._match_row` ainda funciona — só ignora os campos novos por enquanto).

- [ ] **Step 7: Commit**

```bash
git add lolqueue/core/summoner_history.py tests/test_summoner_history.py tests/test_history_page.py
git commit -m "feat: MatchSummary traz itens, runas, feitiços, nível e gold"
```

---

## Task 2: `ItemCatalog`

**Files:**
- Create: `lolqueue/core/items.py`
- Modify: `lolqueue/lcu/endpoints.py`
- Test: `tests/test_items.py`

**Interfaces:**
- Consumes: `endpoints.ITEMS` (novo), `LcuError` de `lolqueue.lcu.client`.
- Produces: `ItemCatalog(client)` com `.load()`, `.loaded: bool`, `.icon_path(item_id: int) -> str`, `.icons() -> list[str]`.

- [ ] **Step 1: Escrever o teste**

Criar `tests/test_items.py`:

```python
"""O catálogo de itens: ícone por id, carregado uma vez do cliente."""

from lolqueue.core.items import ItemCatalog
from lolqueue.lcu import endpoints

from .fakes import FakeLcuClient

#: Recorte de `/lol-game-data/assets/v1/items.json`, com dados reais.
ITEMS = [
    {
        "id": 3153,
        "iconPath": "/lol-game-data/assets/ASSETS/Items/Icons2D/3153_Fighter_T3_BladeOfTheRuinedKing.png",
    },
    {"id": 1001, "iconPath": "/lol-game-data/assets/ASSETS/Items/Icons2D/1001_Boots.png"},
]


def catalog(responses=None, failures=None):
    client = FakeLcuClient(
        responses={endpoints.ITEMS: ITEMS, **(responses or {})},
        failures=failures,
    )
    loaded = ItemCatalog(client)
    loaded.load()
    return loaded, client


def test_the_catalog_learns_the_icon():
    items, _ = catalog()

    assert items.icon_path(3153) == (
        "/lol-game-data/assets/ASSETS/Items/Icons2D/3153_Fighter_T3_BladeOfTheRuinedKing.png"
    )


def test_an_item_it_never_heard_of_has_no_icon():
    items, _ = catalog()

    assert items.icon_path(404) == ""


def test_a_failed_load_leaves_the_catalog_empty_not_wrong():
    items, _ = catalog(failures={endpoints.ITEMS})

    assert not items.loaded
    assert items.icon_path(3153) == ""


def test_the_catalog_is_only_fetched_once():
    items, client = catalog()
    items.load()

    assert client.paths("GET").count(endpoints.ITEMS) == 1


def test_the_icon_list_has_no_repeats():
    items, _ = catalog()

    paths = items.icons()
    assert len(paths) == len(set(paths))
    assert all(paths)
```

- [ ] **Step 2: Rodar e ver a falha**

Run: `py -m pytest tests/test_items.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lolqueue.core.items'`.

- [ ] **Step 3: Adicionar a rota em `lcu/endpoints.py`**

No fim de `lolqueue/lcu/endpoints.py`, adicionar:

```python
#: Catálogo de itens do patch atual — nome (não usado aqui) e
#: `iconPath` de cada um. Serve para desenhar a grade de itens do
#: histórico de partidas, que só vem com o id.
ITEMS = "/lol-game-data/assets/v1/items.json"
#: Idem, para os feitiços de invocador (Fulgor, Barreira, ...).
SUMMONER_SPELLS = "/lol-game-data/assets/v1/summoner-spells.json"
```

- [ ] **Step 4: Criar `lolqueue/core/items.py`**

```python
"""O catálogo de itens do patch atual, pelo próprio cliente do LoL.

O histórico de partidas do OP.GG só manda o id de cada item; o ícone
para desenhar a grade da linha vem daqui, do mesmo jeito que
`core/perks.py` traz o das runas. Sem nome aqui: a UI já recebe
`items_names` pronto do próprio OP.GG.
"""

from __future__ import annotations

from ..lcu import endpoints
from ..lcu.client import LcuError


class ItemCatalog:
    """Ícone de cada item, por id — carga preguiçosa e tolerante a falha."""

    def __init__(self, client) -> None:
        self._client = client
        self._icons: dict[int, str] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        if self._loaded:
            return
        try:
            items = self._client.get(endpoints.ITEMS)
        except LcuError:
            return
        if not isinstance(items, list):
            return
        found: dict[int, str] = {}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            item_id = entry.get("id")
            if not isinstance(item_id, int):
                continue
            found[item_id] = str(entry.get("iconPath") or "")
        if not found:
            return
        self._icons = found
        self._loaded = True

    def icon_path(self, item_id: int) -> str:
        """O `iconPath` cru do item, ou vazio se não conhecido."""
        return self._icons.get(item_id, "")

    def icons(self) -> list[str]:
        """Todo caminho de imagem que o catálogo conhece, sem repetir."""
        return sorted({path for path in self._icons.values() if path})
```

- [ ] **Step 5: Rodar e ver passar**

Run: `py -m pytest tests/test_items.py -v`
Expected: PASS em todos.

- [ ] **Step 6: Commit**

```bash
git add lolqueue/core/items.py lolqueue/lcu/endpoints.py tests/test_items.py
git commit -m "feat: ItemCatalog resolve icone de item pelo cliente do LoL"
```

---

## Task 3: `SpellCatalog`

**Files:**
- Create: `lolqueue/core/spells.py`
- Test: `tests/test_spells.py`

**Interfaces:**
- Consumes: `endpoints.SUMMONER_SPELLS` (já criado na Task 2).
- Produces: `SpellCatalog(client)` — mesma interface de `ItemCatalog`: `.load()`, `.loaded`, `.icon_path(spell_id: int) -> str`, `.icons() -> list[str]`.

- [ ] **Step 1: Escrever o teste**

Criar `tests/test_spells.py`:

```python
"""O catálogo de feitiços de invocador: ícone por id."""

from lolqueue.core.spells import SpellCatalog
from lolqueue.lcu import endpoints

from .fakes import FakeLcuClient

#: Recorte de `/lol-game-data/assets/v1/summoner-spells.json`, com dados reais.
SPELLS = [
    {"id": 4, "iconPath": "/lol-game-data/assets/DATA/Spells/Icons2D/Summoner_flash.png"},
    {"id": 12, "iconPath": "/lol-game-data/assets/DATA/Spells/Icons2D/Summoner_teleport.png"},
]


def catalog(responses=None, failures=None):
    client = FakeLcuClient(
        responses={endpoints.SUMMONER_SPELLS: SPELLS, **(responses or {})},
        failures=failures,
    )
    loaded = SpellCatalog(client)
    loaded.load()
    return loaded, client


def test_the_catalog_learns_the_icon():
    spells, _ = catalog()

    assert spells.icon_path(4) == "/lol-game-data/assets/DATA/Spells/Icons2D/Summoner_flash.png"


def test_a_spell_it_never_heard_of_has_no_icon():
    spells, _ = catalog()

    assert spells.icon_path(404) == ""


def test_a_failed_load_leaves_the_catalog_empty_not_wrong():
    spells, _ = catalog(failures={endpoints.SUMMONER_SPELLS})

    assert not spells.loaded
    assert spells.icon_path(4) == ""


def test_the_catalog_is_only_fetched_once():
    spells, client = catalog()
    spells.load()

    assert client.paths("GET").count(endpoints.SUMMONER_SPELLS) == 1


def test_the_icon_list_has_no_repeats():
    spells, _ = catalog()

    paths = spells.icons()
    assert len(paths) == len(set(paths))
    assert all(paths)
```

- [ ] **Step 2: Rodar e ver a falha**

Run: `py -m pytest tests/test_spells.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lolqueue.core.spells'`.

- [ ] **Step 3: Criar `lolqueue/core/spells.py`**

```python
"""O catálogo de feitiços de invocador do patch atual, pelo cliente do LoL.

Mesmo desenho de `core/items.py`: o histórico de partidas só manda o
id de cada feitiço, e o ícone para desenhar vem daqui.
"""

from __future__ import annotations

from ..lcu import endpoints
from ..lcu.client import LcuError


class SpellCatalog:
    """Ícone de cada feitiço de invocador, por id."""

    def __init__(self, client) -> None:
        self._client = client
        self._icons: dict[int, str] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        if self._loaded:
            return
        try:
            spells = self._client.get(endpoints.SUMMONER_SPELLS)
        except LcuError:
            return
        if not isinstance(spells, list):
            return
        found: dict[int, str] = {}
        for entry in spells:
            if not isinstance(entry, dict):
                continue
            spell_id = entry.get("id")
            if not isinstance(spell_id, int):
                continue
            found[spell_id] = str(entry.get("iconPath") or "")
        if not found:
            return
        self._icons = found
        self._loaded = True

    def icon_path(self, spell_id: int) -> str:
        return self._icons.get(spell_id, "")

    def icons(self) -> list[str]:
        return sorted({path for path in self._icons.values() if path})
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m pytest tests/test_spells.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add lolqueue/core/spells.py tests/test_spells.py
git commit -m "feat: SpellCatalog resolve icone de feitico pelo cliente do LoL"
```

---

## Task 4: `to_bool` e o placar completo (`GameDetail`)

**Files:**
- Modify: `lolqueue/core/mcp_format.py`
- Modify: `lolqueue/core/summoner_history.py`
- Test: `tests/test_summoner_history.py`

**Interfaces:**
- Produces: `mcp_format.to_bool(value: str) -> bool | None`; dataclasses `ParticipantDetail`, `TeamDetail`, `GameDetail`; `SummonerHistorySource.fetch_game_detail(self, match_id: str, played_at: datetime, region: str, game_name: str, tag_line: str, lang: str = DEFAULT_LANG) -> GameDetail | None`.
- Consumes (Task 6, `GameDetailLoader`): esta assinatura exata de `fetch_game_detail`.

- [ ] **Step 1: Escrever o teste com a resposta real (anonimizada) do `lol_get_summoner_game_detail`**

Em `tests/test_summoner_history.py`, adicionar os imports novos e a constante `GAME_DETAIL`:

```python
from lolqueue.core.summoner_history import (
    GameDetail,
    MatchSummary,
    ParticipantDetail,
    Profile,
    RankEntry,
    SummonerHistorySource,
    TeamDetail,
    relative_time,
)
```

```python
GAME_DETAIL = """class LolGetSummonerGameDetail: data
class Data: game_detail
class GameDetail: id,created_at,game_type,game_length_second,average_tier_info,teams
class AverageTierInfo: tier,division
class Team: key,game_stat,banned_champions,banned_champions_names,participants
class GameStat: is_win,champion_kill,tower_kill,dragon_kill,baron_kill,rift_herald_kill,gold_earned
class Participant: is_target,summoner,champion_id,champion_name,team_key,position,items,items_names,rune,spells,stats
class Summoner: game_name,tagline
class Rune: primary_page_id,primary_rune_id,secondary_page_id
class Stats: champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,total_damage_dealt_to_champions,result

LolGetSummonerGameDetail(Data(GameDetail("wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=","2026-08-23T17:18:49+09:00","SOLORANKED",958,AverageTierInfo("EMERALD",2),[Team("BLUE",GameStat(false,8,0,0,0,0,24155),[25,55,141,412,910],["Morgana","Katarina","Kayn","Thresh","Hwei"],[Participant(false,Summoner("Aliado1","BR1"),200,"Bel'Veth","BLUE","JUNGLE",[1102,6672,1001,2152,1043],["Cria de Andabrisas","Mata-Cráquens","Botas","Elixir da Força","Arco Recurvo"],Rune(8000,8008,8300),[4,11],Stats(8,1,9,0,2,74,4735,2682,"LOSE")),Participant(true,Summoner("Jogador","BR1"),54,"Malphite","BLUE","TOP",[1056,3802,1001,1029,1026],["Anel de Doran","Capítulo Perdido","Botas","Couraça de Pano","Varinha Explosiva"],Rune(8200,8229,8400),[4,12],Stats(10,0,4,0,79,0,3901,4790,"LOSE")),Participant(false,Summoner("Aliado2","BR1"),800,"Mel","BLUE","MID",[6655,3145,1001],["Eco de Luden","Alternador Hextec","Botas"],Rune(8200,8229,8000),[12,4],Stats(10,3,5,2,107,0,4981,8128,"LOSE")),Participant(false,Summoner("Aliado3","BR1"),427,"Ivern","BLUE","SUPPORT",[3870,6617,3158],["Criassonhos","Regenerador de Pedra Lunar","Botas Ionianas da Lucidez"],Rune(8200,8214,8400),[7,4],Stats(7,1,7,4,9,0,4048,2590,"LOSE")),Participant(false,Summoner("Aliado4","BR1"),222,"Jinx","BLUE","ADC",[3144,2523,1086,3086],["Estilingue do Patrulheiro","Hexótica C44","Arco de Doran","Zelo"],Rune(8000,8008,8300),[21,4],Stats(9,3,5,1,116,0,6490,7360,"LOSE"))]),Team("RED",GameStat(true,30,3,1,0,0,36881),[33,117,134,164,238],["Rammus","Lulu","Syndra","Camille","Zed"],[Participant(false,Summoner("Rival1","BR1"),58,"Renekton","RED","TOP",[1055,2031,6692,3111,2021],["Lâmina de Doran","Poção com Refil","Eclipse","Passos de Mercúrio","Tunelizador"],Rune(8000,8010,8400),[4,14],Stats(13,7,0,2,151,2,8471,11033,"WIN")),Participant(false,Summoner("Rival2","BR1"),81,"Ezreal","RED","ADC",[1086,3078,3133,1036,3070],["Arco de Doran","Força da Trindade","Martelo de Guerra de Caulfield","Espada Longa","Lágrima da Deusa"],Rune(8000,8005,8300),[7,4],Stats(11,7,1,3,125,0,8035,10519,"WIN")),Participant(false,Summoner("Rival3","BR1"),526,"Rell","RED","SUPPORT",[3869,3047,3190,1028,1029,1029],["Oposição Celestial","Botas Galvanizadas de Aço","Medalhão dos Solari de Ferro","Cristal de Rubi","Couraça de Pano","Couraça de Pano"],Rune(8400,8439,8300),[4,14],Stats(8,1,5,15,20,0,5317,5007,"WIN")),Participant(false,Summoner("Rival4","BR1"),711,"Vex","RED","MID",[1056,6655,3175,1058,2055],["Anel de Doran","Eco de Luden","Sapatos Enfeitiçados","Bastão Desnecessariamente Grande","Sentinela de Controle"],Rune(8100,8112,8200),[4,14],Stats(11,8,1,5,107,0,7420,11181,"WIN")),Participant(false,Summoner("Rival5","BR1"),234,"Viego","RED","JUNGLE",[6676,6672,1001,1018],["A Coletora","Mata-Cráquens","Botas","Capa da Agilidade"],Rune(8100,9923,8000),[11,4],Stats(11,7,1,5,4,117,7638,9061,"WIN"))])])))"""
```

E o teste:

```python
def test_fetch_game_detail_reads_both_teams_bans_and_the_target_row():
    source = SummonerHistorySource(send=FakeSend(matches_answer=GAME_DETAIL))
    send = FakeSend(matches_answer=GAME_DETAIL)
    source = SummonerHistorySource(send=send)

    detail = source.fetch_game_detail(
        "wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=",
        datetime.fromisoformat("2026-08-23T17:18:49+09:00"),
        "BR",
        "Jogador",
        "BR1",
    )

    assert detail == GameDetail(
        match_id="wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=",
        duration_seconds=958,
        queue_type="SOLORANKED",
        played_at=datetime.fromisoformat("2026-08-23T17:18:49+09:00"),
        teams=(
            TeamDetail(
                key="BLUE",
                win=False,
                kills=8,
                towers=0,
                dragons=0,
                barons=0,
                heralds=0,
                gold=24155,
                banned_champion_ids=(25, 55, 141, 412, 910),
                banned_champion_names=("Morgana", "Katarina", "Kayn", "Thresh", "Hwei"),
                participants=(
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado1",
                        tag_line="BR1",
                        champion_id=200,
                        champion_name="Bel'Veth",
                        team_key="BLUE",
                        position="JUNGLE",
                        items=(1102, 6672, 1001, 2152, 1043),
                        item_names=(
                            "Cria de Andabrisas",
                            "Mata-Cráquens",
                            "Botas",
                            "Elixir da Força",
                            "Arco Recurvo",
                        ),
                        spells=(4, 11),
                        primary_style_id=8000,
                        primary_rune_id=8008,
                        secondary_style_id=8300,
                        champion_level=8,
                        kills=1,
                        deaths=9,
                        assists=0,
                        cs=76,
                        gold=4735,
                        damage_to_champions=2682,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=True,
                        game_name="Jogador",
                        tag_line="BR1",
                        champion_id=54,
                        champion_name="Malphite",
                        team_key="BLUE",
                        position="TOP",
                        items=(1056, 3802, 1001, 1029, 1026),
                        item_names=(
                            "Anel de Doran",
                            "Capítulo Perdido",
                            "Botas",
                            "Couraça de Pano",
                            "Varinha Explosiva",
                        ),
                        spells=(4, 12),
                        primary_style_id=8200,
                        primary_rune_id=8229,
                        secondary_style_id=8400,
                        champion_level=10,
                        kills=0,
                        deaths=4,
                        assists=0,
                        cs=79,
                        gold=3901,
                        damage_to_champions=4790,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado2",
                        tag_line="BR1",
                        champion_id=800,
                        champion_name="Mel",
                        team_key="BLUE",
                        position="MID",
                        items=(6655, 3145, 1001),
                        item_names=("Eco de Luden", "Alternador Hextec", "Botas"),
                        spells=(12, 4),
                        primary_style_id=8200,
                        primary_rune_id=8229,
                        secondary_style_id=8000,
                        champion_level=10,
                        kills=3,
                        deaths=5,
                        assists=2,
                        cs=107,
                        gold=4981,
                        damage_to_champions=8128,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado3",
                        tag_line="BR1",
                        champion_id=427,
                        champion_name="Ivern",
                        team_key="BLUE",
                        position="SUPPORT",
                        items=(3870, 6617, 3158),
                        item_names=(
                            "Criassonhos",
                            "Regenerador de Pedra Lunar",
                            "Botas Ionianas da Lucidez",
                        ),
                        spells=(7, 4),
                        primary_style_id=8200,
                        primary_rune_id=8214,
                        secondary_style_id=8400,
                        champion_level=7,
                        kills=1,
                        deaths=7,
                        assists=4,
                        cs=9,
                        gold=4048,
                        damage_to_champions=2590,
                        result="LOSE",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Aliado4",
                        tag_line="BR1",
                        champion_id=222,
                        champion_name="Jinx",
                        team_key="BLUE",
                        position="ADC",
                        items=(3144, 2523, 1086, 3086),
                        item_names=(
                            "Estilingue do Patrulheiro",
                            "Hexótica C44",
                            "Arco de Doran",
                            "Zelo",
                        ),
                        spells=(21, 4),
                        primary_style_id=8000,
                        primary_rune_id=8008,
                        secondary_style_id=8300,
                        champion_level=9,
                        kills=3,
                        deaths=5,
                        assists=1,
                        cs=116,
                        gold=6490,
                        damage_to_champions=7360,
                        result="LOSE",
                    ),
                ),
            ),
            TeamDetail(
                key="RED",
                win=True,
                kills=30,
                towers=3,
                dragons=1,
                barons=0,
                heralds=0,
                gold=36881,
                banned_champion_ids=(33, 117, 134, 164, 238),
                banned_champion_names=("Rammus", "Lulu", "Syndra", "Camille", "Zed"),
                participants=(
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival1",
                        tag_line="BR1",
                        champion_id=58,
                        champion_name="Renekton",
                        team_key="RED",
                        position="TOP",
                        items=(1055, 2031, 6692, 3111, 2021),
                        item_names=(
                            "Lâmina de Doran",
                            "Poção com Refil",
                            "Eclipse",
                            "Passos de Mercúrio",
                            "Tunelizador",
                        ),
                        spells=(4, 14),
                        primary_style_id=8000,
                        primary_rune_id=8010,
                        secondary_style_id=8400,
                        champion_level=13,
                        kills=7,
                        deaths=0,
                        assists=2,
                        cs=153,
                        gold=8471,
                        damage_to_champions=11033,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival2",
                        tag_line="BR1",
                        champion_id=81,
                        champion_name="Ezreal",
                        team_key="RED",
                        position="ADC",
                        items=(1086, 3078, 3133, 1036, 3070),
                        item_names=(
                            "Arco de Doran",
                            "Força da Trindade",
                            "Martelo de Guerra de Caulfield",
                            "Espada Longa",
                            "Lágrima da Deusa",
                        ),
                        spells=(7, 4),
                        primary_style_id=8000,
                        primary_rune_id=8005,
                        secondary_style_id=8300,
                        champion_level=11,
                        kills=7,
                        deaths=1,
                        assists=3,
                        cs=125,
                        gold=8035,
                        damage_to_champions=10519,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival3",
                        tag_line="BR1",
                        champion_id=526,
                        champion_name="Rell",
                        team_key="RED",
                        position="SUPPORT",
                        items=(3869, 3047, 3190, 1028, 1029, 1029),
                        item_names=(
                            "Oposição Celestial",
                            "Botas Galvanizadas de Aço",
                            "Medalhão dos Solari de Ferro",
                            "Cristal de Rubi",
                            "Couraça de Pano",
                            "Couraça de Pano",
                        ),
                        spells=(4, 14),
                        primary_style_id=8400,
                        primary_rune_id=8439,
                        secondary_style_id=8300,
                        champion_level=8,
                        kills=1,
                        deaths=5,
                        assists=15,
                        cs=20,
                        gold=5317,
                        damage_to_champions=5007,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival4",
                        tag_line="BR1",
                        champion_id=711,
                        champion_name="Vex",
                        team_key="RED",
                        position="MID",
                        items=(1056, 6655, 3175, 1058, 2055),
                        item_names=(
                            "Anel de Doran",
                            "Eco de Luden",
                            "Sapatos Enfeitiçados",
                            "Bastão Desnecessariamente Grande",
                            "Sentinela de Controle",
                        ),
                        spells=(4, 14),
                        primary_style_id=8100,
                        primary_rune_id=8112,
                        secondary_style_id=8200,
                        champion_level=11,
                        kills=8,
                        deaths=1,
                        assists=5,
                        cs=107,
                        gold=7420,
                        damage_to_champions=11181,
                        result="WIN",
                    ),
                    ParticipantDetail(
                        is_target=False,
                        game_name="Rival5",
                        tag_line="BR1",
                        champion_id=234,
                        champion_name="Viego",
                        team_key="RED",
                        position="JUNGLE",
                        items=(6676, 6672, 1001, 1018),
                        item_names=("A Coletora", "Mata-Cráquens", "Botas", "Capa da Agilidade"),
                        spells=(11, 4),
                        primary_style_id=8100,
                        primary_rune_id=9923,
                        secondary_style_id=8000,
                        champion_level=11,
                        kills=7,
                        deaths=1,
                        assists=5,
                        cs=121,
                        gold=7638,
                        damage_to_champions=9061,
                        result="WIN",
                    ),
                ),
            ),
        ),
        average_tier="EMERALD",
    )
    tool, arguments = send.calls[0]
    assert tool == "lol_get_summoner_game_detail"
    assert arguments["game_id"] == "wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg="
    assert arguments["focus_riot_id"] == "Jogador#BR1"


def test_an_empty_response_means_no_game_detail():
    source = SummonerHistorySource(send=FakeSend(matches_answer=""))

    detail = source.fetch_game_detail(
        "id", datetime(2026, 8, 23, tzinfo=timezone.utc), "BR", "Jogador", "BR1"
    )

    assert detail is None


def test_a_network_failure_means_no_game_detail():
    source = SummonerHistorySource(send=FakeSend(fail=True))

    detail = source.fetch_game_detail(
        "id", datetime(2026, 8, 23, tzinfo=timezone.utc), "BR", "Jogador", "BR1"
    )

    assert detail is None
```

Nota: `FakeSend` hoje devolve `matches_answer` para qualquer ferramenta que não seja `lol_get_summoner_profile` (ver `tests/test_summoner_history.py`, classe `FakeSend`) — por isso o teste usa `matches_answer=GAME_DETAIL` para simular a resposta de `lol_get_summoner_game_detail`. Nenhuma mudança em `FakeSend` é necessária.

- [ ] **Step 2: Rodar e ver a falha**

Run: `py -m pytest tests/test_summoner_history.py -v`
Expected: FAIL — `ImportError: cannot import name 'GameDetail'`.

- [ ] **Step 3: Adicionar `to_bool` em `core/mcp_format.py`**

No fim de `lolqueue/core/mcp_format.py`, antes de `send_tool`:

```python
def to_bool(value: str) -> bool | None:
    """Lê o `true`/`false` cru que o servidor manda para booleano.

    Sem aspas e sem `True`/`False` do Python — o valor chega
    exatamente como veio no campo `is_win`/`is_target` da resposta.
    """
    text = value.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    return None
```

- [ ] **Step 4: Adicionar as dataclasses, o parser e `fetch_game_detail` em `core/summoner_history.py`**

Logo abaixo de `MatchSummary`, adicionar:

```python
GAME_DETAIL_TOOL = "lol_get_summoner_game_detail"
GAME_DETAIL_ROOT = "LolGetSummonerGameDetail"

GAME_DETAIL_FIELDS = (
    "data.game_detail.{id,created_at,game_type,game_length_second}",
    "data.game_detail.average_tier_info.tier",
    "data.game_detail.teams[].{key,banned_champions,banned_champions_names}",
    "data.game_detail.teams[].game_stat.{is_win,champion_kill,tower_kill,dragon_kill,baron_kill,rift_herald_kill,gold_earned}",
    "data.game_detail.teams[].participants[].{is_target,champion_id,champion_name,team_key,position,items,items_names,spells}",
    "data.game_detail.teams[].participants[].summoner.{game_name,tagline}",
    "data.game_detail.teams[].participants[].rune.{primary_page_id,primary_rune_id,secondary_page_id}",
    "data.game_detail.teams[].participants[].stats.{champion_level,kill,death,assist,minion_kill,neutral_minion_kill,gold_earned,total_damage_dealt_to_champions,result}",
)


@dataclass(frozen=True)
class ParticipantDetail:
    """Uma linha do placar: quem jogou o quê, e como foi."""

    is_target: bool
    game_name: str
    tag_line: str
    champion_id: int
    champion_name: str
    team_key: str  # "BLUE" | "RED"
    position: str
    items: tuple[int, ...]
    item_names: tuple[str, ...]
    spells: tuple[int, int]
    primary_style_id: int
    primary_rune_id: int
    secondary_style_id: int
    champion_level: int
    kills: int
    deaths: int
    assists: int
    cs: int
    gold: int
    damage_to_champions: int
    result: str  # "WIN" | "LOSE"


@dataclass(frozen=True)
class TeamDetail:
    """Um dos dois lados: o placar do time e quem jogou nele."""

    key: str  # "BLUE" | "RED"
    win: bool
    kills: int
    towers: int
    dragons: int
    barons: int
    heralds: int
    gold: int
    banned_champion_ids: tuple[int, ...]
    banned_champion_names: tuple[str, ...]
    participants: tuple[ParticipantDetail, ...]


@dataclass(frozen=True)
class GameDetail:
    """O placar completo de uma partida: as duas equipes, lado a lado."""

    match_id: str
    duration_seconds: int
    queue_type: str
    played_at: datetime
    teams: tuple[TeamDetail, TeamDetail]
    average_tier: str | None
```

Logo abaixo, os parsers (privados, mesmo estilo de `_rank_entries`/`_profile`):

```python
def _participant_detail(value: str, schema: dict[str, list[str]]) -> ParticipantDetail | None:
    fields = mcp_format.unpack(value, schema)
    if fields is None:
        return None
    is_target = mcp_format.to_bool(fields.get("is_target", ""))
    summoner = mcp_format.unpack(fields.get("summoner"), schema)
    rune = mcp_format.unpack(fields.get("rune"), schema)
    stats = mcp_format.unpack(fields.get("stats"), schema)
    if is_target is None or summoner is None or rune is None or stats is None:
        return None
    game_name = summoner.get("game_name", "").strip().strip('"')
    tag_line = summoner.get("tagline", "").strip().strip('"')
    champion_id = mcp_format.to_int(fields.get("champion_id", ""))
    champion_name = fields.get("champion_name", "").strip().strip('"')
    team_key = fields.get("team_key", "").strip().strip('"')
    position = fields.get("position", "").strip().strip('"')
    items = mcp_format.to_ints(fields.get("items", "[]"))
    spells = mcp_format.to_ints(fields.get("spells", "[]"))
    primary_style_id = mcp_format.to_int(rune.get("primary_page_id", ""))
    primary_rune_id = mcp_format.to_int(rune.get("primary_rune_id", ""))
    secondary_style_id = mcp_format.to_int(rune.get("secondary_page_id", ""))
    champion_level = mcp_format.to_int(stats.get("champion_level", ""))
    kills = mcp_format.to_int(stats.get("kill", ""))
    deaths = mcp_format.to_int(stats.get("death", ""))
    assists = mcp_format.to_int(stats.get("assist", ""))
    minions = mcp_format.to_int(stats.get("minion_kill", "")) or 0
    neutral = mcp_format.to_int(stats.get("neutral_minion_kill", "")) or 0
    gold = mcp_format.to_int(stats.get("gold_earned", ""))
    damage = mcp_format.to_int(stats.get("total_damage_dealt_to_champions", ""))
    result = stats.get("result", "").strip().strip('"')
    if (
        not game_name
        or not tag_line
        or champion_id is None
        or not champion_name
        or items is None
        or spells is None
        or len(spells) != 2
        or primary_style_id is None
        or primary_rune_id is None
        or secondary_style_id is None
        or champion_level is None
        or kills is None
        or deaths is None
        or assists is None
        or gold is None
        or damage is None
        or not result
    ):
        return None
    return ParticipantDetail(
        is_target=is_target,
        game_name=game_name,
        tag_line=tag_line,
        champion_id=champion_id,
        champion_name=champion_name,
        team_key=team_key,
        position=position,
        items=tuple(items),
        item_names=tuple(mcp_format.to_strings(fields.get("items_names", ""))),
        spells=(spells[0], spells[1]),
        primary_style_id=primary_style_id,
        primary_rune_id=primary_rune_id,
        secondary_style_id=secondary_style_id,
        champion_level=champion_level,
        kills=kills,
        deaths=deaths,
        assists=assists,
        cs=minions + neutral,
        gold=gold,
        damage_to_champions=damage,
        result=result,
    )


def _team_detail(value: str, schema: dict[str, list[str]]) -> TeamDetail | None:
    fields = mcp_format.unpack(value, schema)
    if fields is None:
        return None
    key = fields.get("key", "").strip().strip('"')
    stat = mcp_format.unpack(fields.get("game_stat"), schema)
    if not key or stat is None:
        return None
    win = mcp_format.to_bool(stat.get("is_win", ""))
    kills = mcp_format.to_int(stat.get("champion_kill", ""))
    towers = mcp_format.to_int(stat.get("tower_kill", ""))
    dragons = mcp_format.to_int(stat.get("dragon_kill", ""))
    barons = mcp_format.to_int(stat.get("baron_kill", ""))
    heralds = mcp_format.to_int(stat.get("rift_herald_kill", ""))
    gold = mcp_format.to_int(stat.get("gold_earned", ""))
    banned_ids = mcp_format.to_ints(fields.get("banned_champions", "[]"))
    if (
        win is None
        or kills is None
        or towers is None
        or dragons is None
        or barons is None
        or heralds is None
        or gold is None
        or banned_ids is None
    ):
        return None
    participants: list[ParticipantDetail] = []
    for entry in mcp_format.entries(fields.get("participants", "")):
        detail = _participant_detail(entry, schema)
        if detail is not None:
            participants.append(detail)
    if len(participants) != 5:
        return None
    return TeamDetail(
        key=key,
        win=win,
        kills=kills,
        towers=towers,
        dragons=dragons,
        barons=barons,
        heralds=heralds,
        gold=gold,
        banned_champion_ids=tuple(banned_ids),
        banned_champion_names=tuple(mcp_format.to_strings(fields.get("banned_champions_names", ""))),
        participants=tuple(participants),
    )


def _game_detail(text: str) -> GameDetail | None:
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, GAME_DETAIL_ROOT)
    if data is None:
        return None
    game = mcp_format.unpack(data.get("game_detail"), schema)
    if game is None:
        return None
    match_id = game.get("id", "").strip().strip('"')
    created_at = game.get("created_at", "").strip().strip('"')
    queue_type = game.get("game_type", "").strip().strip('"')
    duration = mcp_format.to_int(game.get("game_length_second", ""))
    if not match_id or not created_at or duration is None:
        return None
    try:
        played_at = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    tier_fields = mcp_format.unpack(game.get("average_tier_info"), schema) or {}
    tier_raw = tier_fields.get("tier", "").strip()
    average_tier = tier_raw.strip('"') if tier_raw and tier_raw != "null" else None
    teams: list[TeamDetail] = []
    for entry in mcp_format.entries(game.get("teams", "")):
        team = _team_detail(entry, schema)
        if team is not None:
            teams.append(team)
    if len(teams) != 2:
        return None
    return GameDetail(
        match_id=match_id,
        duration_seconds=duration,
        queue_type=queue_type,
        played_at=played_at,
        teams=(teams[0], teams[1]),
        average_tier=average_tier,
    )
```

Por fim, o método novo em `SummonerHistorySource` (logo após `fetch_matches`):

```python
    def fetch_game_detail(
        self,
        match_id: str,
        played_at: datetime,
        region: str,
        game_name: str,
        tag_line: str,
        lang: str = DEFAULT_LANG,
    ) -> GameDetail | None:
        if not match_id or not region or not game_name or not tag_line:
            return None
        try:
            text = self._send(
                GAME_DETAIL_TOOL,
                {
                    "region": region,
                    "game_id": match_id,
                    "created_at": played_at.isoformat(),
                    "game_name": game_name,
                    "tag_line": tag_line,
                    "focus_riot_id": f"{game_name}#{tag_line}",
                    "lang": lang,
                    "desired_output_fields": list(GAME_DETAIL_FIELDS),
                },
            )
        except Exception:
            return None
        return _game_detail(text or "")
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `py -m pytest tests/test_summoner_history.py -v`
Expected: PASS em todos.

- [ ] **Step 6: Rodar a suíte inteira**

Run: `py -m pytest -q`
Expected: PASS em todos os testes.

- [ ] **Step 7: Commit**

```bash
git add lolqueue/core/mcp_format.py lolqueue/core/summoner_history.py tests/test_summoner_history.py
git commit -m "feat: fetch_game_detail traz o placar completo de uma partida"
```

---

## Task 5: `IconLoader` carrega itens e feitiços

**Files:**
- Modify: `lolqueue/ui/icon_loader.py`

**Interfaces:**
- Consumes: `ItemCatalog` (Task 2), `SpellCatalog` (Task 3).
- Produces: `IconLoader.catalogs_ready = Signal(object, object)` — `(ItemCatalog, SpellCatalog)`.

Sem teste unitário próprio (mesmo padrão de `_load_perks` hoje — thin wrapper de `QThread`, ver Global Constraints). A verificação é rodar a suíte inteira (nenhuma regressão) e, no fim, a verificação ao vivo.

- [ ] **Step 1: Editar `lolqueue/ui/icon_loader.py`**

Adicionar aos imports:

```python
from ..core.items import ItemCatalog
from ..core.spells import SpellCatalog
```

Adicionar o sinal novo, logo abaixo de `perks_ready`:

```python
    #: `(ItemCatalog, SpellCatalog)`, os dois já com os ícones no disco.
    catalogs_ready = Signal(object, object)
```

Em `run()`, chamar o método novo depois de `_load_perks`:

```python
    def run(self) -> None:
        credentials = discover()
        if credentials is None:
            return
        client = LcuClient(credentials, timeout=5.0)
        self._store.fetch_missing(client, self._ids, lambda: self._running)
        self._load_perks(client)
        self._load_catalogs(client)
        if self._running:
            self.done.emit()
```

E o método novo, logo depois de `_load_perks`:

```python
    def _load_catalogs(self, client) -> None:
        """Itens e feitiços do histórico de partidas — mesma natureza dos perks.

        Independente do catálogo de runas: uma falha ali não impede a
        grade de itens de funcionar, e vice-versa.
        """
        if self._assets is None or not self._running:
            return
        items = ItemCatalog(client)
        items.load()
        spells = SpellCatalog(client)
        spells.load()
        if not items.loaded or not spells.loaded:
            return
        self._assets.fetch_missing(client, items.icons(), lambda: self._running)
        self._assets.fetch_missing(client, spells.icons(), lambda: self._running)
        if self._running:
            self.catalogs_ready.emit(items, spells)
```

- [ ] **Step 2: Rodar a suíte inteira**

Run: `py -m pytest -q`
Expected: PASS em todos (nada consome `IconLoader` diretamente nos testes hoje — só `test_window.py` via `FakeLoader`, que não é afetado).

- [ ] **Step 3: Commit**

```bash
git add lolqueue/ui/icon_loader.py
git commit -m "feat: IconLoader tambem carrega itens e feiticos"
```

---

## Task 6: `GameDetailLoader`

**Files:**
- Create: `lolqueue/ui/game_detail_loader.py`

**Interfaces:**
- Consumes: `SummonerHistorySource.fetch_game_detail(match_id, played_at, region, game_name, tag_line)` (Task 4), `current_identity(client)`, `MatchSummary`.
- Produces: `GameDetailLoader(source, match, parent=None)` com `ready = Signal(object)` (`GameDetail | None`).

Sem teste unitário próprio (mesmo padrão de `HistoryLoader`/`MatchupLoader` — ver Global Constraints).

- [ ] **Step 1: Criar `lolqueue/ui/game_detail_loader.py`**

```python
"""Busca o placar completo de uma partida fora da thread da tela.

Mesmo molde do `HistoryLoader`: abre a própria conexão com o cliente
do LoL, descobre a identidade atual (a região vem de lá) e só então
consulta o OP.GG. Uma consulta por vez — quem garante isso é a janela,
que só cria um loader novo se o anterior já terminou.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.identity import current_identity
from ..core.summoner_history import GameDetail, MatchSummary, SummonerHistorySource
from ..lcu.client import LcuClient
from ..lcu.credentials import discover


class GameDetailLoader(QThread):
    #: `GameDetail | None`. `object` porque é uma classe nossa e pode
    #: vir `None` quando a consulta falha.
    ready = Signal(object)

    def __init__(
        self, source: SummonerHistorySource, match: MatchSummary, parent=None
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._match = match

    def run(self) -> None:
        detail: GameDetail | None = None
        try:
            credentials = discover()
            if credentials is not None:
                client = LcuClient(credentials)
                identity = current_identity(client)
                if identity is not None:
                    detail = self._source.fetch_game_detail(
                        self._match.match_id,
                        self._match.played_at,
                        identity.region,
                        identity.game_name,
                        identity.tag_line,
                    )
        except Exception:
            # Cliente fechado no meio da consulta, DNS falhando, o que
            # for: quem chama só precisa saber que não há placar agora.
            detail = None
        self.ready.emit(detail)
```

- [ ] **Step 2: Rodar a suíte inteira**

Run: `py -m pytest -q`
Expected: PASS em todos (módulo novo, ainda não referenciado por ninguém).

- [ ] **Step 3: Commit**

```bash
git add lolqueue/ui/game_detail_loader.py
git commit -m "feat: GameDetailLoader busca o placar completo fora da tela"
```

---

## Task 7: Estilo — faixa de resultado, selo de nível, destaque do jogador

**Files:**
- Modify: `lolqueue/ui/theme.py`
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces: seletores QSS `#optionCard[result="win"]`, `#optionCard[result="lose"]`, `#optionCard[target="true"]`, `#levelBadge`, `#itemIcon`, `#runeIcon`, `#spellIcon` — nenhuma API Python nova.

- [ ] **Step 1: Escrever o teste**

Em `tests/test_theme.py`, adicionar:

```python
def test_the_match_result_stripe_uses_win_and_loss_colors():
    assert Palette.ACTIVE in STYLESHEET
    assert Palette.DANGER in STYLESHEET
    assert '#optionCard[result="win"]' in STYLESHEET
    assert '#optionCard[result="lose"]' in STYLESHEET


def test_the_targeted_player_row_has_its_own_highlight():
    assert '#optionCard[target="true"]' in STYLESHEET
```

- [ ] **Step 2: Rodar e ver a falha**

Run: `py -m pytest tests/test_theme.py -v`
Expected: FAIL — os dois testes novos falham (seletores ainda não existem no `STYLESHEET`).

- [ ] **Step 3: Adicionar as regras em `lolqueue/ui/theme.py`**

Logo depois do bloco `#optionCard { ... }` (linhas 187-191 hoje), adicionar:

```python
#optionCard[result="win"] {{ border-left: 3px solid {Palette.ACTIVE}; }}
#optionCard[result="lose"] {{ border-left: 3px solid {Palette.DANGER}; }}
#optionCard[target="true"] {{
    background: rgba(200, 170, 110, 40);
    border: 1px solid rgba(200, 170, 110, 140);
}}
#levelBadge {{
    background: {Palette.SURFACE_HIGH};
    color: {Palette.TEXT};
    border: 1px solid {Palette.BORDER};
    border-radius: 3px;
    font-size: 10px;
    font-weight: 700;
}}
#itemIcon, #runeIcon, #spellIcon {{
    background: {Palette.SURFACE};
    border: 1px solid rgba(127, 165, 198, 54);
    border-radius: 3px;
}}
```

(As regras `#optionCard { ... }` seguem valendo como base; as três de cima só ajustam borda/fundo por cima, então a ordem — logo depois do bloco base — importa para o `border-left` do resultado não ser sobrescrito de volta pela borda cheia do card.)

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m pytest tests/test_theme.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m pytest -q`
Expected: PASS em todos.

- [ ] **Step 6: Commit**

```bash
git add lolqueue/ui/theme.py tests/test_theme.py
git commit -m "feat: estilo do resultado, selo de nivel e destaque do jogador"
```

---

## Task 8: `HistoryPage` — linha de partida no estilo do cliente

**Files:**
- Modify: `lolqueue/ui/pages/history.py`
- Test: `tests/test_history_page.py`

**Interfaces:**
- Produces: `HistoryPage.match_selected = Signal(object)` (`MatchSummary`); `set_item_icon_resolver(resolve)`, `set_spell_icon_resolver(resolve)`, `set_keystone_icon_resolver(resolve)`, `set_secondary_style_icon_resolver(resolve)`; `_ClickableFrame(QFrame)` local ao módulo com `clicked = Signal()`.
- Consumes: `MatchSummary` estendido (Task 1).

- [ ] **Step 1: Escrever os testes novos**

Em `tests/test_history_page.py`, trocar o import do `QtWidgets` (já existe `pytest.importorskip`, sem mudança) e adicionar, depois de `from PySide6.QtWidgets import ...` — não há import direto de widgets Qt no arquivo hoje além de `QtWidgets` via `pytest.importorskip`; usar `QtWidgets.QLabel`/`QtWidgets.QFrame` diretamente nos testes novos, sem import extra. Adicionar ao fim do arquivo:

```python
def test_the_match_row_shows_as_many_item_icons_as_the_match_has(page):
    page.set_history(profile(), (match(items=(1001, 1002, 1003)),))
    row = page._matches_box.itemAt(0).widget()

    icons = row.findChildren(QtWidgets.QLabel)
    item_icons = [w for w in icons if w.objectName() == "itemIcon"]

    assert len(item_icons) == 3


def test_a_win_gets_the_win_color_and_a_loss_gets_the_loss_color(page):
    page.set_history(
        profile(),
        (match(match_id="a", result="WIN"), match(match_id="b", result="LOSE")),
    )

    rows = [page._matches_box.itemAt(i).widget() for i in range(2)]

    assert rows[0].property("result") == "win"
    assert rows[1].property("result") == "lose"


def test_clicking_a_row_asks_to_open_that_match(page):
    seen = []
    page.match_selected.connect(seen.append)
    chosen = match()
    page.set_history(profile(), (chosen,))
    row = page._matches_box.itemAt(0).widget()

    row.clicked.emit()

    assert seen == [chosen]
```

- [ ] **Step 2: Rodar e ver a falha**

Run: `py -m pytest tests/test_history_page.py -v`
Expected: FAIL — `AttributeError: 'QFrame' object has no attribute 'clicked'` (ou `property("result")` vindo vazio) e `objectName() == "itemIcon"` não bate com nada.

- [ ] **Step 3: Reescrever a linha de partida em `lolqueue/ui/pages/history.py`**

Adicionar a classe `_ClickableFrame` logo abaixo de `_duration_text`:

```python
class _ClickableFrame(QFrame):
    """Um `QFrame` que também avisa quando alguém clica nele."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
```

Adicionar as constantes de tamanho de ícone, junto de `MATCH_PORTRAIT`:

```python
MATCH_PORTRAIT = QSize(40, 40)
LEVEL_BADGE = QSize(18, 14)
RUNE_ICON = QSize(18, 18)
SPELL_ICON = QSize(18, 18)
ITEM_ICON = QSize(20, 20)
```

No `__init__` de `HistoryPage`, adicionar o sinal e os resolvedores novos:

```python
class HistoryPage(QWidget):
    refresh_requested = Signal()
    #: A tela pede para abrir o placar de uma partida específica.
    match_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resolve_icon = None
        self._resolve_name = None
        self._resolve_item_icon = None
        self._resolve_spell_icon = None
        self._resolve_keystone_icon = None
        self._resolve_secondary_icon = None
```

(o resto do `__init__` continua igual por enquanto — a visão de placar entra na Task 9).

Adicionar os quatro setters novos, logo depois de `set_name_resolver`:

```python
    def set_item_icon_resolver(self, resolve) -> None:
        self._resolve_item_icon = resolve

    def set_spell_icon_resolver(self, resolve) -> None:
        self._resolve_spell_icon = resolve

    def set_keystone_icon_resolver(self, resolve) -> None:
        self._resolve_keystone_icon = resolve

    def set_secondary_style_icon_resolver(self, resolve) -> None:
        self._resolve_secondary_icon = resolve
```

Adicionar os quatro helpers de desenho, logo antes de `_match_row`:

```python
    def _portrait_with_level(self, champion_id: int, level: int) -> QWidget:
        holder = QWidget()
        holder.setFixedSize(MATCH_PORTRAIT)
        portrait = QLabel(holder)
        portrait.setGeometry(0, 0, MATCH_PORTRAIT.width(), MATCH_PORTRAIT.height())
        portrait.setScaledContents(True)
        path = self._resolve_icon(champion_id) if self._resolve_icon else None
        icon = QIcon(path) if path else QIcon()
        portrait.setPixmap(icon.pixmap(MATCH_PORTRAIT))
        badge = QLabel(str(level), holder)
        badge.setObjectName("levelBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setGeometry(
            MATCH_PORTRAIT.width() - LEVEL_BADGE.width(),
            MATCH_PORTRAIT.height() - LEVEL_BADGE.height(),
            LEVEL_BADGE.width(),
            LEVEL_BADGE.height(),
        )
        return holder

    def _rune_icons(self, primary_rune_id: int, secondary_style_id: int) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        for rune_id, resolve in (
            (primary_rune_id, self._resolve_keystone_icon),
            (secondary_style_id, self._resolve_secondary_icon),
        ):
            icon_label = QLabel()
            icon_label.setFixedSize(RUNE_ICON)
            icon_label.setScaledContents(True)
            icon_label.setObjectName("runeIcon")
            path = resolve(rune_id) if resolve else None
            icon = QIcon(path) if path else QIcon()
            icon_label.setPixmap(icon.pixmap(RUNE_ICON))
            column.addWidget(icon_label)
        return holder

    def _spell_icons(self, spells) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        for spell_id in spells:
            icon_label = QLabel()
            icon_label.setFixedSize(SPELL_ICON)
            icon_label.setScaledContents(True)
            icon_label.setObjectName("spellIcon")
            path = self._resolve_spell_icon(spell_id) if self._resolve_spell_icon else None
            icon = QIcon(path) if path else QIcon()
            icon_label.setPixmap(icon.pixmap(SPELL_ICON))
            column.addWidget(icon_label)
        return holder

    def _item_icons(self, items) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        for item_id in items:
            icon_label = QLabel()
            icon_label.setFixedSize(ITEM_ICON)
            icon_label.setScaledContents(True)
            icon_label.setObjectName("itemIcon")
            path = self._resolve_item_icon(item_id) if self._resolve_item_icon else None
            icon = QIcon(path) if path else QIcon()
            icon_label.setPixmap(icon.pixmap(ITEM_ICON))
            row.addWidget(icon_label)
        return holder
```

Trocar `_match_row` inteiro:

```python
    def _match_row(self, match, now) -> QFrame:
        row = _ClickableFrame()
        row.setObjectName("optionCard")
        row.setProperty("result", "win" if match.result == "WIN" else "lose")
        row.clicked.connect(lambda: self.match_selected.emit(match))
        box = QHBoxLayout(row)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(10)

        box.addWidget(self._portrait_with_level(match.champion_id, match.champion_level))
        box.addWidget(self._spell_icons(match.spells))
        box.addWidget(self._rune_icons(match.primary_rune_id, match.secondary_style_id))
        box.addWidget(self._item_icons(match.items))

        naming = QVBoxLayout()
        naming.setSpacing(1)
        name = self._resolve_name(match.champion_id) if self._resolve_name else None
        champion = QLabel(name or match.champion_name)
        champion.setObjectName("predictionName")
        naming.addWidget(champion)
        result = "Vitória" if match.result == "WIN" else "Derrota"
        mode = QUEUE_LABELS.get(match.queue_type, match.queue_type)
        detail = QLabel(f"{result} · {mode}")
        detail.setObjectName("heroDetail")
        naming.addWidget(detail)
        box.addLayout(naming)
        box.addStretch(1)

        kda = QLabel(f"{match.kills}/{match.deaths}/{match.assists}")
        kda.setObjectName("cardValue")
        box.addWidget(kda)

        cs = QLabel(f"{match.cs} CS")
        cs.setObjectName("heroDetail")
        box.addWidget(cs)

        gold = QLabel(f"{match.gold} ouro")
        gold.setObjectName("heroDetail")
        box.addWidget(gold)

        duration = QLabel(_duration_text(match.duration_seconds))
        duration.setObjectName("heroDetail")
        box.addWidget(duration)

        when = QLabel(relative_time(match.played_at, now))
        when.setObjectName("hint")
        box.addWidget(when)
        return row
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `py -m pytest tests/test_history_page.py -v`
Expected: PASS em todos, incluindo `test_the_match_row_shows_champion_and_kda` (nome e KDA continuam em `naming`/`box`, alcançáveis pelo `collect` recursivo do teste).

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m pytest -q`
Expected: PASS em todos.

- [ ] **Step 6: Commit**

```bash
git add lolqueue/ui/pages/history.py tests/test_history_page.py
git commit -m "feat: linha de partida no estilo do cliente do LoL"
```

---

## Task 9: `HistoryPage` — placar completo (aba "Placar")

**Files:**
- Modify: `lolqueue/ui/pages/history.py`
- Test: `tests/test_history_page.py`

**Interfaces:**
- Produces: `HistoryPage.set_game_detail(detail: GameDetail | None) -> None`; `HistoryPage._show_list() -> None`.
- Consumes: `GameDetail`/`TeamDetail`/`ParticipantDetail` (Task 4).

- [ ] **Step 1: Escrever os testes e os helpers de fixture**

Em `tests/test_history_page.py`, trocar o bloco de import de `lolqueue.core.summoner_history`:

```python
from lolqueue.core.summoner_history import (  # noqa: E402
    GameDetail,
    MatchSummary,
    ParticipantDetail,
    Profile,
    RankEntry,
    TeamDetail,
)
```

Adicionar os helpers `participant`, `team` e `detail`, logo depois de `match(...)`:

```python
def participant(**changes):
    base = dict(
        is_target=False,
        game_name="Jogador",
        tag_line="BR1",
        champion_id=22,
        champion_name="Ashe",
        team_key="BLUE",
        position="ADC",
        items=(1001, 1002),
        item_names=("Botas", "Espada Longa"),
        spells=(4, 12),
        primary_style_id=8200,
        primary_rune_id=8229,
        secondary_style_id=8400,
        champion_level=15,
        kills=6,
        deaths=6,
        assists=12,
        cs=188,
        gold=8902,
        damage_to_champions=15000,
        result="WIN",
    )
    base.update(changes)
    return ParticipantDetail(**base)


def team(**changes):
    base = dict(
        key="BLUE",
        win=True,
        kills=30,
        towers=8,
        dragons=2,
        barons=1,
        heralds=1,
        gold=55000,
        banned_champion_ids=(1, 2, 3, 4, 5),
        banned_champion_names=("Yone", "Zed", "Akali", "Katarina", "Fizz"),
        participants=tuple(participant(champion_id=i) for i in range(5)),
    )
    base.update(changes)
    return TeamDetail(**base)


def detail(**changes):
    base = dict(
        match_id="abc",
        duration_seconds=1686,
        queue_type="SOLORANKED",
        played_at=datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc),
        teams=(
            team(key="BLUE", win=True),
            team(
                key="RED",
                win=False,
                participants=tuple(
                    participant(champion_id=i, team_key="RED", result="LOSE")
                    for i in range(5, 10)
                ),
            ),
        ),
        average_tier="EMERALD",
    )
    base.update(changes)
    return GameDetail(**base)
```

E os testes, ao fim do arquivo:

```python
def test_a_game_detail_replaces_the_list_with_the_scoreboard(page):
    page.set_history(profile(), (match(),))

    page.set_game_detail(detail())

    assert not page._scoreboard.isHidden()
    assert page._content.isHidden()


def test_going_back_shows_the_list_again(page):
    page.set_history(profile(), (match(),))
    page.set_game_detail(detail())

    page._show_list()

    assert not page._content.isHidden()
    assert page._scoreboard.isHidden()


def test_a_failed_detail_fetch_keeps_the_list(page):
    page.set_history(profile(), (match(),))

    page.set_game_detail(None)

    assert not page._content.isHidden()
    assert page._scoreboard.isHidden()


def test_the_scoreboard_shows_both_teams_with_five_players_each(page):
    page.set_game_detail(detail())

    assert page._teams_box.count() == 2
    first_team_block = page._teams_box.itemAt(0).widget()
    rows = [w for w in first_team_block.findChildren(QtWidgets.QFrame) if w.objectName() == "optionCard"]
    assert len(rows) == 5


def test_the_targeted_player_gets_highlighted(page):
    marked = detail(
        teams=(
            team(
                key="BLUE",
                win=True,
                participants=tuple(
                    participant(champion_id=i, is_target=(i == 0)) for i in range(5)
                ),
            ),
            team(
                key="RED",
                win=False,
                participants=tuple(
                    participant(champion_id=i, team_key="RED", result="LOSE")
                    for i in range(5, 10)
                ),
            ),
        )
    )

    page.set_game_detail(marked)

    first_team_block = page._teams_box.itemAt(0).widget()
    rows = [w for w in first_team_block.findChildren(QtWidgets.QFrame) if w.objectName() == "optionCard"]
    assert rows[0].property("target") == "true"
    assert rows[1].property("target") in (None, "")
```

- [ ] **Step 2: Rodar e ver a falha**

Run: `py -m pytest tests/test_history_page.py -v`
Expected: FAIL — `AttributeError: 'HistoryPage' object has no attribute 'set_game_detail'`.

- [ ] **Step 3: Adicionar a visão de placar em `lolqueue/ui/pages/history.py`**

No `__init__`, logo depois de `content.addStretch(1)` (fim da construção da lista), adicionar:

```python
        self._scoreboard = self._build_scoreboard()
        layout.addWidget(self._scoreboard)
        self._scoreboard.hide()
```

Adicionar os métodos novos, depois de `_match_row`:

```python
    def _build_scoreboard(self) -> QWidget:
        board = QWidget()
        box = QVBoxLayout(board)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(14)

        header = QHBoxLayout()
        back = QPushButton("← Voltar")
        back.setObjectName("primaryButton")
        back.clicked.connect(self._show_list)
        header.addWidget(back)
        header.addStretch(1)
        self._board_summary = QLabel()
        self._board_summary.setObjectName("heroHeadline")
        header.addWidget(self._board_summary)
        box.addLayout(header)

        self._teams_box = QVBoxLayout()
        self._teams_box.setSpacing(18)
        box.addLayout(self._teams_box)
        box.addStretch(1)
        return board

    def _show_list(self) -> None:
        self._scoreboard.hide()
        self._content.show()

    def set_game_detail(self, detail) -> None:
        """Troca a lista pelo placar completo da partida, ou volta à lista.

        `detail` vindo `None` é "a consulta falhou" — a lista continua
        na tela, como se o clique nunca tivesse acontecido.
        """
        if detail is None:
            self._show_list()
            return
        target = None
        for team in detail.teams:
            for participant in team.participants:
                if participant.is_target:
                    target = participant
        result_text = "Vitória" if target is not None and target.result == "WIN" else "Derrota"
        mode = QUEUE_LABELS.get(detail.queue_type, detail.queue_type)
        self._board_summary.setText(
            f"{result_text} · {mode} · {_duration_text(detail.duration_seconds)}"
        )
        self._fill_teams(detail.teams)
        self._content.hide()
        self._scoreboard.show()

    def _fill_teams(self, teams) -> None:
        while self._teams_box.count():
            item = self._teams_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for team in teams:
            self._teams_box.addWidget(self._team_block(team))

    def _team_block(self, team) -> QFrame:
        block = QFrame()
        block.setObjectName("heroCard")
        box = QVBoxLayout(block)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)

        header = QHBoxLayout()
        label = "Vitória" if team.win else "Derrota"
        title = QLabel(f"{label} · {team.kills} abates · {team.gold} ouro")
        title.setObjectName("heroHeadline")
        header.addWidget(title)
        header.addStretch(1)
        objectives = QLabel(
            f"Torres {team.towers} · Dragões {team.dragons} · "
            f"Barões {team.barons} · Arautos {team.heralds}"
        )
        objectives.setObjectName("heroDetail")
        header.addWidget(objectives)
        box.addLayout(header)

        if team.banned_champion_names:
            bans = QLabel("Banidos: " + ", ".join(team.banned_champion_names))
            bans.setObjectName("hint")
            box.addWidget(bans)

        for participant in team.participants:
            box.addWidget(self._participant_row(participant))
        return block

    def _participant_row(self, participant) -> QFrame:
        row = QFrame()
        row.setObjectName("optionCard")
        row.setProperty("result", "win" if participant.result == "WIN" else "lose")
        if participant.is_target:
            row.setProperty("target", "true")
        box = QHBoxLayout(row)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(10)

        box.addWidget(
            self._portrait_with_level(participant.champion_id, participant.champion_level)
        )
        box.addWidget(self._spell_icons(participant.spells))
        box.addWidget(
            self._rune_icons(participant.primary_rune_id, participant.secondary_style_id)
        )

        naming = QVBoxLayout()
        naming.setSpacing(1)
        name = self._resolve_name(participant.champion_id) if self._resolve_name else None
        champion = QLabel(name or participant.champion_name)
        champion.setObjectName("predictionName")
        naming.addWidget(champion)
        who = QLabel(f"{participant.game_name}#{participant.tag_line}")
        who.setObjectName("hint")
        naming.addWidget(who)
        box.addLayout(naming)

        box.addWidget(self._item_icons(participant.items))
        box.addStretch(1)

        kda = QLabel(f"{participant.kills}/{participant.deaths}/{participant.assists}")
        kda.setObjectName("cardValue")
        box.addWidget(kda)

        cs = QLabel(f"{participant.cs} CS")
        cs.setObjectName("heroDetail")
        box.addWidget(cs)

        gold = QLabel(f"{participant.gold} ouro")
        gold.setObjectName("heroDetail")
        box.addWidget(gold)
        return row
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `py -m pytest tests/test_history_page.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m pytest -q`
Expected: PASS em todos.

- [ ] **Step 6: Commit**

```bash
git add lolqueue/ui/pages/history.py tests/test_history_page.py
git commit -m "feat: placar completo da partida, igual ao cliente do LoL"
```

---

## Task 10: `MainWindow` — fiação completa e atualização automática

**Files:**
- Modify: `lolqueue/ui/window.py`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: tudo das Tasks 1-9 (`ItemCatalog`, `SpellCatalog`, `IconLoader.catalogs_ready`, `GameDetailLoader`, `HistoryPage.match_selected`/`set_item_icon_resolver`/`set_spell_icon_resolver`/`set_keystone_icon_resolver`/`set_secondary_style_icon_resolver`/`set_game_detail`).
- Produces: `MainWindow._open_game_detail(match)`, `_retire_game_detail_loader(loader)`, `_on_game_detail_ready(detail)`, `_on_catalogs_ready(items, spells)`, `_item_icon(item_id)`, `_spell_icon(spell_id)`, `_match_keystone_icon(rune_id)`, `_match_tree_icon(style_id)`.

- [ ] **Step 1: Escrever os testes novos**

Em `tests/test_window.py`, adicionar ao fim (reaproveitando `FakeLoader` já definida no arquivo):

```python
# --- histórico e placar ---------------------------------------------------


def test_the_history_refreshes_itself_when_a_match_ends(window, monkeypatch):
    chamadas = []
    monkeypatch.setattr(window, "_refresh_history", lambda: chamadas.append(True))

    window._on_phase_changed("EndOfGame")

    assert chamadas == [True]


def test_other_phase_changes_do_not_refresh_the_history(window, monkeypatch):
    chamadas = []
    monkeypatch.setattr(window, "_refresh_history", lambda: chamadas.append(True))

    window._on_phase_changed("InProgress")

    assert chamadas == []


def test_a_finished_game_detail_loader_is_let_go(window):
    loader = FakeLoader()
    window._game_detail_loader = loader

    window._retire_game_detail_loader(loader)

    assert window._game_detail_loader is None
    assert loader.descartado


def test_a_late_game_detail_loader_does_not_discard_the_current_one(window):
    velho, atual = FakeLoader(), FakeLoader()
    window._game_detail_loader = atual

    window._retire_game_detail_loader(velho)

    assert window._game_detail_loader is atual
    assert velho.descartado


def test_open_game_detail_does_nothing_when_one_is_already_running(window):
    loader = FakeLoader()
    window._game_detail_loader = loader

    window._open_game_detail(None)

    assert window._game_detail_loader is loader


def test_a_ready_game_detail_reaches_the_history_page(window, monkeypatch):
    seen = []
    monkeypatch.setattr(window._history, "set_game_detail", lambda detail: seen.append(detail))

    window._on_game_detail_ready("placar-falso")

    assert seen == ["placar-falso"]
```

- [ ] **Step 2: Rodar e ver a falha**

Run: `py -m pytest tests/test_window.py -v`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_game_detail_loader'` (e `_refresh_history` sendo chamado incondicionalmente, já que hoje `_on_phase_changed` não olha para `EndOfGame`).

- [ ] **Step 3: Editar `lolqueue/ui/window.py`**

Adicionar o import novo, junto dos outros de `.`:

```python
from .game_detail_loader import GameDetailLoader
```

No `__init__`, logo depois de `self._perks = None`, adicionar:

```python
        # Os catálogos de item e feitiço, para a grade do histórico —
        # mesmo motivo do `_perks`: dado estático do cliente, sobrevive
        # a uma reconexão.
        self._items = None
        self._spells = None
```

Logo depois de `self._icon_loader: IconLoader | None = None`, adicionar:

```python
        self._game_detail_loader: GameDetailLoader | None = None
```

Em `_build()`, trocar o bloco da `self._history`:

```python
        self._history = HistoryPage()
        self._history.set_icon_resolver(self._champion_icon)
        self._history.set_name_resolver(self._champion_name)
        self._history.set_item_icon_resolver(self._item_icon)
        self._history.set_spell_icon_resolver(self._spell_icon)
        self._history.set_keystone_icon_resolver(self._match_keystone_icon)
        self._history.set_secondary_style_icon_resolver(self._match_tree_icon)
        self._history.refresh_requested.connect(self._refresh_history)
        self._history.match_selected.connect(self._open_game_detail)
```

Em `_start_icon_loader`, trocar a condição de saída antecipada e a fiação do loader:

```python
    def _start_icon_loader(self, catalog: ChampionCatalog) -> None:
        ids = [champion_id for champion_id, _ in catalog.all()]
        if self._icon_loader is not None:
            return
        faltam = self._icons.missing(ids)
        tudo_carregado = (
            self._perks is not None and self._items is not None and self._spells is not None
        )
        if not faltam and tudo_carregado:
            return
        if faltam:
            self._log_message("Baixando os retratos dos campeões…")
        self._icon_loader = IconLoader(ids, self._icons, self._assets, self)
        self._icon_loader.done.connect(self._on_icons_ready)
        self._icon_loader.perks_ready.connect(self._on_perks_ready)
        self._icon_loader.catalogs_ready.connect(self._on_catalogs_ready)
        self._icon_loader.start()
```

Adicionar `_on_catalogs_ready`, logo depois de `_on_perks_ready`:

```python
    def _on_catalogs_ready(self, items, spells) -> None:
        """Entrega os catálogos de item e feitiço para o histórico desenhar a grade."""
        self._items = items
        self._spells = spells
```

Adicionar os quatro resolvedores, logo depois de `_rune_icon`:

```python
    def _item_icon(self, item_id: int) -> str | None:
        """Onde o ícone daquele item ficou no disco, se ficou."""
        if self._items is None:
            return None
        path = self._items.icon_path(item_id)
        return self._rune_icon(path) if path else None

    def _spell_icon(self, spell_id: int) -> str | None:
        """Onde o ícone daquele feitiço ficou no disco, se ficou."""
        if self._spells is None:
            return None
        path = self._spells.icon_path(spell_id)
        return self._rune_icon(path) if path else None

    def _match_keystone_icon(self, rune_id: int) -> str | None:
        """Onde o ícone daquela runa-chave ficou no disco, se ficou."""
        if self._perks is None:
            return None
        return self._rune_icon(self._perks.perk(rune_id).icon)

    def _match_tree_icon(self, style_id: int) -> str | None:
        """Onde o ícone daquela árvore secundária ficou no disco, se ficou."""
        if self._perks is None:
            return None
        style = self._perks.style(style_id)
        return self._rune_icon(style.icon) if style is not None else None
```

Em `_on_phase_changed`, adicionar o gatilho de atualização automática logo antes de `self._refresh_ring()`:

```python
        if phase_value == GameflowPhase.END_OF_GAME.value:
            # Pedido do usuário: o histórico não pode depender do
            # clique em "Atualizar" para saber que uma partida acabou.
            self._refresh_history()
        self._refresh_ring()
```

Adicionar `_open_game_detail`, `_retire_game_detail_loader` e `_on_game_detail_ready`, logo depois de `_retire_history_loader`/`_on_history_ready`:

```python
    def _open_game_detail(self, match) -> None:
        """Busca o placar completo de uma partida numa thread só dela.

        Uma consulta por vez, como o histórico: clicar em duas partidas
        rápido não deve empilhar duas buscas ao mesmo tempo.
        """
        if self._game_detail_loader is not None:
            return
        loader = GameDetailLoader(self._history_source, match, self)
        loader.ready.connect(self._on_game_detail_ready)
        loader.finished.connect(lambda: self._retire_game_detail_loader(loader))
        self._game_detail_loader = loader
        loader.start()

    def _retire_game_detail_loader(self, loader) -> None:
        if self._game_detail_loader is loader:
            self._game_detail_loader = None
        loader.deleteLater()

    def _on_game_detail_ready(self, detail) -> None:
        self._history.set_game_detail(detail)
```

Em `closeEvent`, adicionar a espera pelo loader novo, logo depois do bloco de `_history_loader`:

```python
        if self._history_loader is not None:
            self._history_loader.wait(3000)
        if self._game_detail_loader is not None:
            self._game_detail_loader.wait(3000)
        event.accept()
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `py -m pytest tests/test_window.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m pytest -q`
Expected: PASS em todos os testes do projeto.

- [ ] **Step 6: Commit**

```bash
git add lolqueue/ui/window.py tests/test_window.py
git commit -m "feat: liga placar nativo e atualizacao automatica do historico"
```

---

## Task 11: Limpeza, build e verificação ao vivo

**Files:**
- Delete: `_probe_matches.txt`, `_probe_detail_schema.json`, `_probe_detail.txt`, `_lol_native_history.png`, `_lol_native_expanded.png` (raiz do projeto — arquivos de referência temporários usados só para desenhar este plano).

- [ ] **Step 1: Rodar a suíte inteira uma última vez**

Run: `py -m pytest -q`
Expected: PASS em todos os testes (baseline anterior era 549; o número sobe com os testes novos das Tasks 1-10).

- [ ] **Step 2: Remover os arquivos de sonda temporários**

```bash
git rm -f _probe_matches.txt _probe_detail_schema.json _probe_detail.txt _lol_native_history.png _lol_native_expanded.png
```

Se algum desses arquivos nunca foi commitado (eram só rascunho local), usar `rm -f <arquivo>` em vez de `git rm -f` para o que não estiver rastreado.

- [ ] **Step 3: Commit da limpeza**

```bash
git commit -m "chore: remove arquivos de sonda usados no design do placar nativo"
```

- [ ] **Step 4: Fechar a instância aberta do app**

Verificar se o app está rodando e encerrar o processo (ex.: `Get-Process` no PowerShell, ou fechar pela bandeja/janela). Confirmar que não há mais processo do LoL Queue ativo antes de reconstruir — dois processos gravando no mesmo `config.json`/log ao mesmo tempo pode corromper o arquivo.

- [ ] **Step 5: Gerar o build novo**

Rodar o comando de build já usado pelo projeto (mesmo script/target do fechamento de features anteriores desta sessão — conferir `README`/`pyproject.toml`/script de build existente no repositório antes de rodar, para usar exatamente o comando já estabelecido, sem inventar um novo).

- [ ] **Step 6: Abrir o build novo**

Executar o binário/gerado e confirmar que a janela abre sem erro no log.

- [ ] **Step 7: Verificação visual ao vivo**

Com o cliente do LoL aberto ao lado (conta Princee#adc, mesma usada nos testes):
1. Navegar até "Histórico" no app.
2. Comparar a lista de partidas com a tela de histórico nativa do cliente: retrato+selo de nível, itens, runas, gold, faixa de cor do resultado.
3. Clicar numa partida e comparar o placar aberto com a aba "Placar" nativa: duas equipes, bans, objetivos, os 10 jogadores, destaque na própria linha.
4. Conferir que os dados da partida clicada batem com os já usados nos testes (mesmo `match_id` da partida real, `wgqT90Iiz71ynmfE2gGrOoe_IuLqM3MEUMF1WEiWzAg=`, quando ela ainda aparecer no histórico da conta).
5. Terminar (ou simular o fim de) uma partida e confirmar que o histórico se atualiza sozinho, sem precisar clicar em "Atualizar".

Reportar ao usuário qualquer diferença visual encontrada nesta etapa antes de considerar a feature concluída — ajustes finos de estilo (cores, espaçamento, tamanho de ícone) são esperados e devem ser corrigidos aqui, com uma volta rápida a `ui/theme.py`/`ui/pages/history.py` se necessário.

---

## Self-Review (já aplicado ao escrever este plano)

- **Cobertura do spec:** Objetivo 1 (linha da lista) → Tasks 1, 8. Objetivo 2 (placar completo) → Tasks 4, 6, 9, 10. Objetivo 3 (atualização automática) → Task 10. Objetivo 4 (fechar/reconstruir/reabrir + verificação ao vivo) → Task 11. Seção "Fora de escopo" respeitada: nenhuma task toca Visão Geral/Estatísticas/Gráficos/Runas do cliente nem `op_score_timeline`, e a atualização automática usa o `phase_changed` que o watcher já emite, sem polling novo.
- **Placeholders:** nenhum "TBD"/"implementar depois" — todo passo de código tem o código completo; testes têm asserts concretos com valores reais extraídos da captura ao vivo.
- **Consistência de tipos:** `fetch_game_detail(match_id, played_at, region, game_name, tag_line, lang=...)` é chamado com essa assinatura exata tanto na Task 4 (definição) quanto na Task 6 (`GameDetailLoader.run`, via `self._match.match_id`/`self._match.played_at`/`identity.region`/`identity.game_name`/`identity.tag_line`). `GameDetail.teams`/`TeamDetail.participants`/`ParticipantDetail` usam os mesmos nomes de campo em `core/summoner_history.py` (Task 4), `ui/pages/history.py` (Task 9, `_team_block`/`_participant_row`) e nos testes (Task 9, helpers `team()`/`participant()`/`detail()`). Os quatro `set_*_resolver` de `HistoryPage` (Task 8) têm os nomes exatos que `window.py` chama na Task 10.
