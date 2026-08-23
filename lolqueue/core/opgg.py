"""Runas, feitiços e itens do OP.GG.

A Riot recomenda o que os designers acham bom; o OP.GG mede o que
venceu. Este módulo pega a segunda opinião pelo servidor MCP oficial do
OP.GG — `mcp-api.op.gg`, aberto, sem chave — e devolve as nove runas,
os dois feitiços e os blocos de itens prontos para o cliente.

O formato de resposta (compacto, não-JSON) é lido por
`core/mcp_format.py`, compartilhado com `core/summoner_history.py`.

**Nada aqui é obrigatório.** Toda falha — rede fora, campeão
desconhecido, formato mudado, modo sem dados — vira ``None``, e quem
chama volta para a recomendação da Riot. É a razão de este módulo não
levantar exceção nenhuma para fora.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from . import mcp_format

ENDPOINT = "https://mcp-api.op.gg/mcp"
TOOL = "lol_get_champion_analysis"

#: Faixa de elo consultada. Diamante+ é o corte onde a amostra ainda é
#: grande e as escolhas já são deliberadas.
TIER = "diamond_plus"

#: Sintaxe do próprio servidor: `[]` marca campo de lista. Sem isso ele
#: recusa o pedido e devolve um diagnóstico em vez de dados.
#:
#: As sinergias vêm por rota, e as rotas disponíveis mudam conforme a
#: posição do campeão: um meio recebe `jungle`, `adc` e `support`, e
#: `mid` é recusado — ele não faz dupla consigo mesmo. Pedir as cinco e
#: deixar o servidor descartar o que não se aplica é mais simples do que
#: manter aqui uma tabela de quem combina com quem; o descarte é
#: gracioso, vem anotado em `_field_diagnostics` e não atrapalha o
#: resto da resposta.
FIELDS = (
    "data.runes[]",
    "data.summoner_spells[]",
    "data.starter_items[]",
    "data.boots[]",
    "data.core_items[]",
    "data.fourth_items[]",
    "data.fifth_items[]",
    "data.sixth_items[]",
    "data.last_items[]",
    "data.skills[]",
    "data.skill_masteries[]",
    "data.strong_counters[]",
    "data.weak_counters[]",
    "data.synergies.top[]",
    "data.synergies.jungle[]",
    "data.synergies.mid[]",
    "data.synergies.adc[]",
    "data.synergies.support[]",
    "data.summary.average_stats",
    "data.damage_type",
)

#: Os blocos do arsenal, na ordem em que se compra. O rótulo é o que
#: aparece na loja, dentro da partida.
ITEM_BLOCKS = (
    ("starter_items", "Iniciais"),
    ("boots", "Botas"),
    ("core_items", "Principais"),
    ("fourth_items", "4º item"),
    ("fifth_items", "5º item"),
    ("sixth_items", "6º item"),
    ("last_items", "Último item"),
)

#: Os campos que formam o build inteiro, iguais em toda página. Os
#: outros são escolhas entre alternativas, e cada uma vira uma página.
#: Quem separa os dois grupos é esta lista, não quantas alternativas o
#: OP.GG mandou: um slot situacional com uma opção só continua sendo
#: situacional, e tem que ficar no lugar dele na ordem da loja.
CORE_FIELDS = frozenset({"starter_items", "boots", "core_items"})

#: O rótulo do bloco que junta os slots do quarto item em diante. Eles
#: chegam separados do OP.GG e vão juntos para a loja, na ordem de
#: compra: ver `_pages`.
SITUATIONAL_LABEL = "Situacionais"

#: Os dois critérios que os dados sustentam, e que dão nome às páginas.
#: O OP.GG mede cada slot por uso e por vitória, então estas duas
#: leituras existem de verdade; uma terceira aba seria numeração sem
#: dizer o que muda entre uma e outra.
MOST_PLAYED_LABEL = "Mais jogada"
BEST_RATE_LABEL = "Maior taxa"

#: Amostra mínima para um item disputar a página da maior taxa. Sem
#: piso, um slot de três partidas elege o que venceu a única que jogou
#: — foi assim que "Banshee's Veil — 100% de vitórias" virou
#: recomendação principal. Quando nenhum item do slot alcança o piso,
#: o slot repete o mais jogado; se isso acontecer em todos, as duas
#: páginas coincidem e o arsenal sai com uma aba só, que é a resposta
#: honesta para dado insuficiente.
MIN_SAMPLE = 30

#: Os dois modos com dados: fila ranqueada e Abismo. Normal e URF
#: existem no servidor mas voltam vazios.
RIFT_MODE = "RANKED"
ARAM_MODE = "ARAM"

#: A posição é obrigatória no pedido, mas no ARAM não muda nada:
#: verificado contra o servidor, as cinco rotas devolvem o mesmo.
ARAM_LANE = "MID"

#: O LCU chama as rotas de um jeito, o OP.GG de outro.
POSITIONS = {
    "top": "TOP",
    "jungle": "JUNGLE",
    "middle": "MID",
    "bottom": "ADC",
    "utility": "SUPPORT",
}

#: Quantas runas o cliente espera: quatro da árvore principal, duas da
#: secundária, três fragmentos.
PERK_COUNT = 9

#: A chamada que embrulha a resposta inteira.
ROOT = "LolGetChampionAnalysis"


@dataclass(frozen=True)
class Block:
    """Um bloco do arsenal: o rótulo na loja e o que comprar nele.

    `games` é o tamanho da amostra que mediu este bloco, e existe para
    ordenar alternativas. Sem ele a ordem sairia por taxa de vitória
    pura, e um item de três partidas com 100% passaria na frente do que
    todo mundo compra — conselho fabricado a partir de ruído.
    """

    label: str
    items: tuple[int, ...]
    win_rate: float
    games: int = 0


@dataclass(frozen=True)
class Page:
    """Uma página do arsenal: por que ela existe, e o que comprar nela.

    `label` é o critério que a montou, e vai para o título do conjunto
    na loja — é ele que distingue uma aba da outra durante a partida.
    Fica vazio quando só há uma página: aí não existe escolha a
    sinalizar, e o rótulo seria ruído no nome da aba.
    """

    label: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Counter:
    """Um confronto medido: quanto o nosso campeão venceu contra aquele.

    `win_rate` é sempre a taxa do **nosso** campeão, nunca a do outro.
    O servidor manda as duas, e ainda um terceiro campo `win_rate` que
    troca de dono conforme a lista — vale a do adversário quando ele é
    quem vence. Guardar sempre o mesmo lado é o que deixa as duas
    listas comparáveis na tela.
    """

    champion_id: int
    champion: str
    win_rate: float
    games: int


@dataclass(frozen=True)
class Synergy:
    """Um campeão que costuma vencer junto com o nosso, e em que rota."""

    champion_id: int
    champion: str
    position: str
    win_rate: float
    games: int


@dataclass(frozen=True)
class Stats:
    """O boletim do campeão no elo consultado.

    `tier` e `rank` são a nota do OP.GG: tier 1 é o topo, e `rank` é a
    colocação entre todos os campeões da rota.
    """

    games: int
    win_rate: float
    pick_rate: float
    ban_rate: float
    kda: float
    tier: int
    rank: int


@dataclass(frozen=True)
class Build:
    """O que o cliente precisa para montar página, feitiços e arsenal.

    `pages` é uma página de arsenal por critério de leitura: a build
    mais jogada e a de maior taxa de vitória. Cada slot situacional é
    resolvido pelo ranking que o OP.GG já mede — nunca por uma
    combinação que ele não tenha medido.

    Do `skill_order` para baixo é tudo material de leitura: nada disso
    o cliente sabe aplicar sozinho. A ordem de habilidade, em especial,
    não tem endpoint no LCU — dá para mostrar, não para montar. Por
    isso esses campos são opcionais e falham para vazio, enquanto runas
    e feitiços continuam sendo tudo-ou-nada: perder a grade de counters
    não estraga uma partida, entrar com meia página de runas estraga.
    """

    style: int
    sub_style: int
    perks: tuple[int, ...]
    spells: tuple[int, int]
    pages: tuple[Page, ...] = ()
    skill_order: tuple[str, ...] = ()
    skill_max: tuple[str, ...] = ()
    strong_against: tuple[Counter, ...] = ()
    weak_against: tuple[Counter, ...] = ()
    synergies: tuple[Synergy, ...] = ()
    stats: Stats | None = None
    damage_type: str = ""


def _letters(value: str) -> tuple[str, ...]:
    """A sequência de habilidades, `["Q","E","W"]`, já sem as aspas.

    Só passa o que de fato nomeia uma habilidade. O campo é desenhado
    na tela como letra, e um valor estranho vindo do servidor viraria
    um quadradinho vazio no meio da ordem em vez de um erro visível.
    """
    letters = tuple(entry.upper() for entry in mcp_format.to_strings(value))
    if not letters or any(letter not in ("Q", "W", "E", "R") for letter in letters):
        return ()
    return letters


def _counters(value: str | None, schema: dict[str, list[str]]) -> tuple[Counter, ...]:
    """Uma das duas listas de confronto, a favor ou contra.

    O servidor etiqueta as duas como `StrongCounter`; quem diz qual é
    qual é a posição em `Data`, não o nome. Aqui as duas passam pela
    mesma leitura, e o sentido vem de quem chamou.
    """
    if value is None:
        return ()
    found: list[Counter] = []
    for entry in mcp_format.entries(value):
        fields = mcp_format.unpack(entry, schema)
        if fields is None:
            continue
        champion_id = mcp_format.to_int(fields.get("champion_id", ""))
        name = fields.get("champion_name", "").strip().strip('"')
        rate = mcp_format.to_float(fields.get("my_win_rate", ""))
        if champion_id is None or not name or rate is None:
            continue
        found.append(
            Counter(
                champion_id=champion_id,
                champion=name,
                win_rate=rate,
                games=mcp_format.to_int(fields.get("play", "")) or 0,
            )
        )
    return tuple(found)


def _synergies(value: str | None, schema: dict[str, list[str]]) -> tuple[Synergy, ...]:
    """As duplas que vencem junto, de todas as rotas que vieram.

    O servidor agrupa por rota e o agrupamento muda conforme a posição
    do campeão. Em vez de confiar no nome do grupo, cada entrada diz a
    própria rota em `synergy_position` — então dá para achatar tudo
    numa lista só e continuar sabendo quem joga onde.
    """
    if value is None:
        return ()
    groups = mcp_format.unpack(value, schema)
    if groups is None:
        return ()
    found: list[Synergy] = []
    for lane in groups.values():
        for entry in mcp_format.entries(lane):
            fields = mcp_format.unpack(entry, schema)
            if fields is None:
                continue
            champion_id = mcp_format.to_int(fields.get("synergy_champion_id", ""))
            name = fields.get("synergy_champion_name", "").strip().strip('"')
            rate = mcp_format.to_float(fields.get("win_rate", ""))
            if champion_id is None or not name or rate is None:
                continue
            found.append(
                Synergy(
                    champion_id=champion_id,
                    champion=name,
                    position=fields.get("synergy_position", "").strip().strip('"'),
                    win_rate=rate,
                    games=mcp_format.to_int(fields.get("play", "")) or 0,
                )
            )
    return tuple(found)


def _stats(value: str | None, schema: dict[str, list[str]]) -> Stats | None:
    """O boletim, que chega embrulhado num `Summary`."""
    summary = mcp_format.unpack(value, schema)
    if summary is None:
        return None
    fields = mcp_format.unpack(summary.get("average_stats"), schema)
    if fields is None:
        return None
    games = mcp_format.to_int(fields.get("play", ""))
    win_rate = mcp_format.to_float(fields.get("win_rate", ""))
    if games is None or win_rate is None:
        return None
    return Stats(
        games=games,
        win_rate=win_rate,
        pick_rate=mcp_format.to_float(fields.get("pick_rate", "")) or 0.0,
        ban_rate=mcp_format.to_float(fields.get("ban_rate", "")) or 0.0,
        kda=mcp_format.to_float(fields.get("kda", "")) or 0.0,
        tier=mcp_format.to_int(fields.get("tier", "")) or 0,
        rank=mcp_format.to_int(fields.get("rank", "")) or 0,
    )


def _field_options(
    entries: list[str], label: str, schema: dict[str, list[str]]
) -> list[Block]:
    """As alternativas de um campo, cada uma como o seu próprio bloco.

    A etiqueta é a do campo, sem o nome do item junto. Houve aqui um
    `named` que produzia "4º item: Zhonya's Hourglass" para distinguir
    uma aba da outra; desde que os slots situacionais passaram a ir num
    bloco só, `_pages` descarta essa etiqueta e monta a sua própria.
    """
    options: list[Block] = []
    for entry in entries:
        fields = mcp_format.unpack(entry, schema)
        if fields is None:
            continue
        ids = mcp_format.to_ints(fields.get("ids", ""))
        if not ids:
            continue
        play = mcp_format.to_int(fields.get("play", "")) or 0
        win = mcp_format.to_int(fields.get("win", "")) or 0
        options.append(
            Block(
                label=label,
                items=tuple(ids),
                win_rate=win / play if play else 0.0,
                games=play,
            )
        )
    return options


def _slot_choice(options: list[Block], by_rate: bool) -> Block:
    """A opção deste slot para uma das duas páginas.

    `options` chega ordenado por amostra, então o mais jogado é o
    primeiro. Para a página da maior taxa só concorre quem passou de
    `MIN_SAMPLE`; se ninguém passou, o slot repete o mais jogado em vez
    de eleger o campeão de três partidas.
    """
    if not by_rate:
        return options[0]
    solid = [block for block in options if block.games >= MIN_SAMPLE]
    if not solid:
        return options[0]
    return max(solid, key=lambda block: (block.win_rate, block.games))


def _situational(chosen: list[Block], core: Iterable[int] = ()) -> tuple[int, ...]:
    """Os slots situacionais na ordem de compra, sem item repetido.

    Um mesmo item pode encabeçar dois slots — o OP.GG mede cada um por
    conta, e Zhonya's lidera tanto o 4º quanto o 6º. Em blocos
    separados isso só parecia estranho; numa lista de compra única
    viraria "compre Zhonya's duas vezes", que o jogo não permite.

    `core` é o que os blocos anteriores já mandaram comprar, e sai
    daqui pelo mesmo motivo. A estatística de "6º item" conta também
    quem montou o núcleo tarde, então o OP.GG devolve Malignance como
    sexto item da Annie — que é o primeiro item dela. Na loja isso
    apareceria como o mesmo lendário em dois blocos.
    """
    items: list[int] = list(core)
    guarded = len(items)
    for block in chosen:
        items.extend(item for item in block.items if item not in items)
    return tuple(items[guarded:])


def _pages(
    data: dict[str, str], schema: dict[str, list[str]]
) -> tuple[Page, ...]:
    """Monta as páginas do arsenal com o que veio na resposta.

    Item é enfeite: se um campo faltar ou vier vazio, ele some e o
    resto segue. `starter_items`, `boots` e `core_items` chegam como um
    valor só — o núcleo do build, igual em toda página.

    **Os slots finais viram um bloco só.** Do quarto item em diante o
    OP.GG manda alternativas por slot, e havia aqui um bloco por slot:
    a loja ficava com "4º item", "5º item", "6º item" e "Último item"
    lado a lado, cada um com um único item dentro. Ler aquilo durante a
    partida era catar item em quatro títulos separados. Agora a
    sequência inteira vai num bloco `SITUATIONAL_LABEL`, na ordem em
    que se compra, como fazem os outros apps do gênero.

    **As páginas são critérios, não posições.** Havia aqui uma página
    por alternativa — a primeira com a melhor de cada slot, a segunda
    com a seguinte —, e o número da aba não dizia o que mudava dentro
    dela. Agora são duas leituras do mesmo dado, cada uma com nome: a
    build mais jogada e a de maior taxa. Quando as duas dão no mesmo
    conjunto, sai uma aba só, sem rótulo — não havia escolha a
    oferecer.
    """
    core: list[Block] = []
    situational: list[list[Block]] = []
    for field, label in ITEM_BLOCKS:
        raw = data.get(field)
        if raw is None:
            continue
        is_core = field in CORE_FIELDS
        options = _field_options(mcp_format.entries(raw), label, schema)
        if not options:
            continue
        if is_core:
            core.append(options[0])
        else:
            options.sort(key=lambda block: (block.games, block.win_rate), reverse=True)
            situational.append(options)

    if not situational:
        if not core:
            return ()
        return (Page(label="", blocks=tuple(core)),)

    # O que o núcleo já compra não volta na lista situacional.
    comprado = tuple(item for block in core for item in block.items)

    pages: list[Page] = []
    seen: set[frozenset[int]] = set()
    for label, by_rate in ((MOST_PLAYED_LABEL, False), (BEST_RATE_LABEL, True)):
        items = _situational(
            [_slot_choice(o, by_rate) for o in situational], comprado
        )
        if not items:
            continue
        assinatura = frozenset(items)
        if assinatura in seen:
            continue
        seen.add(assinatura)
        pages.append(
            Page(
                label=label,
                blocks=tuple(core)
                + (
                    Block(
                        label=SITUATIONAL_LABEL,
                        items=items,
                        # Taxa e amostra ficam de fora: são de cada item,
                        # e estampar a de um só no título do bloco inteiro
                        # daria a entender que vale para todos.
                        win_rate=0.0,
                        games=0,
                    ),
                ),
            )
        )

    if len(pages) == 1:
        # Critério só nomeia o que se contrapõe a outro. Sozinho na
        # loja, "Mais jogada" sugeriria uma segunda aba que não existe.
        pages = [Page(label="", blocks=pages[0].blocks)]
    return tuple(pages)


def parse_build(text: str) -> Build | None:
    """Lê a resposta do OP.GG. Devolve ``None`` se faltar runa ou feitiço.

    Meia recomendação é pior que nenhuma: entrar em partida com três
    runas certas e o resto em branco é um estrago silencioso. Por isso
    a página é tudo-ou-nada. Os itens seguem regra própria, mais frouxa,
    porque um bloco a menos na loja não estraga nada.
    """
    schema = mcp_format.schema(text)
    data = mcp_format.root_data(text, schema, ROOT)
    if data is None:
        return None

    runes = mcp_format.unpack(mcp_format.first(data.get("runes")), schema)
    spells = mcp_format.unpack(mcp_format.first(data.get("summoner_spells")), schema)
    if runes is None or spells is None:
        return None

    style = mcp_format.to_int(runes.get("primary_page_id", ""))
    sub_style = mcp_format.to_int(runes.get("secondary_page_id", ""))
    primary = mcp_format.to_ints(runes.get("primary_rune_ids", ""))
    secondary = mcp_format.to_ints(runes.get("secondary_rune_ids", ""))
    shards = mcp_format.to_ints(runes.get("stat_mod_ids", ""))
    chosen = mcp_format.to_ints(spells.get("ids", ""))

    if style is None or sub_style is None:
        return None
    if primary is None or secondary is None or shards is None:
        return None
    if chosen is None or len(chosen) < 2:
        return None

    perks = tuple(primary + secondary + shards)
    if len(perks) != PERK_COUNT:
        return None

    skills = mcp_format.unpack(mcp_format.first(data.get("skills")), schema)
    masteries = mcp_format.unpack(mcp_format.first(data.get("skill_masteries")), schema)

    return Build(
        style=style,
        sub_style=sub_style,
        perks=perks,
        spells=(chosen[0], chosen[1]),
        pages=_pages(data, schema),
        skill_order=_letters(skills.get("order", "")) if skills else (),
        skill_max=_letters(masteries.get("ids", "")) if masteries else (),
        strong_against=_counters(data.get("strong_counters"), schema),
        weak_against=_counters(data.get("weak_counters"), schema),
        synergies=_synergies(data.get("synergies"), schema),
        stats=_stats(data.get("summary"), schema),
        damage_type=(data.get("damage_type") or "").strip().strip('"'),
    )


def _send(arguments: dict) -> str:
    """Chama a ferramenta de análise de campeão e devolve o texto da resposta."""
    return mcp_format.send_tool(ENDPOINT, TOOL, arguments)


class OpggSource:
    """Busca a recomendação do OP.GG, com memória do que já perguntou.

    O cache vale enquanto o app estiver aberto. Não é otimização de
    rede: é para o mesmo campeão na mesma rota não custar segundos de
    novo numa seleção seguinte.
    """

    def __init__(self, send: Callable[[dict], str] | None = None) -> None:
        self._send = send or _send
        self._cache: dict[tuple[str, str, str], Build] = {}

    def fetch(
        self, champion: str, position: str | None, aram: bool, tier: str = TIER
    ) -> Build | None:
        """Runas, feitiços e itens deste campeão nesta rota, ou ``None``.

        Na Fenda, sem rota não há pergunta a fazer: o OP.GG exige a
        posição, e no modo cego o cliente não atribui nenhuma. No
        Abismo é o contrário — ninguém tem rota, e o servidor devolve
        a mesma resposta para todas elas, então qualquer uma serve
        para satisfazer o campo obrigatório.

        `tier` é o elo escolhido nos ajustes — o cache entra por ele
        também, senão trocar o elo em pleno app continuaria devolvendo
        a build do elo anterior para um campeão já perguntado.
        """
        if not champion:
            return None

        if aram:
            mode, lane, key = ARAM_MODE, ARAM_LANE, (champion, ARAM_MODE, tier)
        else:
            lane = POSITIONS.get((position or "").lower())
            if lane is None:
                return None
            mode, key = RIFT_MODE, (champion, lane, tier)
        if key in self._cache:
            return self._cache[key]

        try:
            text = self._send(
                {
                    "champion": champion,
                    "position": lane,
                    "game_mode": mode,
                    "tier": tier,
                    "lang": "en_US",
                    "desired_output_fields": list(FIELDS),
                }
            )
        except Exception:
            # A rede é o caminho normal de falha aqui, e falhar é
            # aceitável: quem chama tem a Riot de reserva. Guardar o
            # erro no cache seria condenar a sessão inteira.
            return None

        build = parse_build(text or "")
        if build is not None:
            self._cache[key] = build
        return build
