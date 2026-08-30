"""O guia de confronto do OP.GG: você contra o adversário da sua rota.

É a mesma casa do `opgg`, outra ferramenta — `lol_get_lane_matchup_guide`
—, e aqui a resposta **é** JSON de verdade, não o formato compacto. Por
isso este módulo existe separado: são dois protocolos, e misturá-los no
mesmo parser deixaria os dois piores.

**O que o confronto muda, e o que não muda.** Medido contra o servidor
com Yasuo no meio: a build *do topo* — a runa mais jogada, o item mais
comprado — é a mesma vs. Zed, vs. Malzahar e vs. Annie, embora a
amostra caia de 2722 para 557 partidas. O que muda é a cauda: a ordem e
a composição das alternativas de cada slot mudam de adversário para
adversário, e é justamente aí que mora o conselho.

**Por que esta consulta virou a fonte principal da build.** Havia aqui
a conclusão de que ela "não serve para trocar build, serviria para
repetir a que já temos". Estava certa sobre o topo e errada sobre o
resto, e o resto é quase tudo o que importa: o `champion_analysis`
devolve **uma** opção de cada coisa (uma página de runa, um núcleo de
itens, um par de feitiços), enquanto esta devolve cinco páginas de
runa, os itens abertos por profundidade de compra com todas as
alternativas medidas de cada degrau, `single_runes` por encaixe com
amostra muito maior (534 contra 286) e as estatísticas de cada uma.
Sem alternativa não há escolha, e sem escolha o app estava
apresentando "o mais jogado" como se fosse "o melhor" — que é o
problema que este módulo passou a resolver.

**O que continua vindo do `champion_analysis`.** Esta ferramenta exige
`opponent_champion`, e não aceita curinga: sem saber contra quem se
joga (escolha às cegas, ARAM, começo do draft) ela não responde. Aí a
build volta a sair do `opgg`, mais pobre e inteira. Ver `Matchup.build`,
que é ``None`` sempre que a leitura rica não fecha.

**Só responde em inglês.** Com `lang="pt_BR"` o servidor devolve zero
caractere — não um erro, uma resposta vazia. A dica chega em inglês e é
mostrada assim; traduzir por conta própria seria inventar conselho de
jogo em cima de texto que ninguém revisou.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import ranking
from .buildblocks import Block, extras, slot
from .opgg import Build, Page, RunePage, Stats

TOOL = "lol_get_lane_matchup_guide"

#: O servidor devolve o nome do campeão que leva vantagem, ou esta
#: palavra quando a rota é parelha.
EVEN = "EVEN"

#: Como o OP.GG nomeia o ritmo sugerido, e como se diz aqui.
PLAY_STYLES = {
    "aggressive": "Agressivo",
    "even": "Equilibrado",
    "defensive": "Defensivo",
    "passive": "Cauteloso",
}

#: Os blocos que abrem a lista de compra, antes dos lendários.
STARTER_LABEL = "Iniciais"
BOOTS_LABEL = "Botas"

#: `last_items` não é a última compra: é o ranking dos itens mais
#: construídos, e a amostra dele costuma ser maior que a do primeiro
#: degrau. O rótulo antigo, "Último item", mandava fechar a build com
#: item de começo de partida. Ver `opgg.EXTRA_LABEL`, que é o mesmo
#: campo pelo mesmo motivo — o vocabulário da loja é um só.
EXTRA_LABEL = "Situacionais"

#: `single_items` vem aberto por `depth`: a profundidade da compra.
#: Cada degrau é um bloco da loja, e é o que aparece lado a lado
#: durante a partida.
DEPTH_LABELS = {
    1: "1º item",
    2: "2º item",
    3: "3º item",
    4: "4º item",
    5: "5º item",
}

#: Os dois critérios que dão nome às páginas de runa, os mesmos do
#: arsenal em `opgg` — o vocabulário da tela é um só.
MOST_PLAYED_LABEL = "Mais jogada"
BEST_RATE_LABEL = "Maior taxa"

#: Quantas runas uma página completa tem: 4 da árvore primária, 2 da
#: secundária e 3 fragmentos. Página com outra contagem é descartada
#: inteira — meia página de runa é pior que nenhuma.
PERK_COUNT = 9


@dataclass(frozen=True)
class Matchup:
    """O que muda quando se sabe contra quem se está jogando.

    `lane_advantage` e `solo_kill_advantage` guardam o nome do campeão
    favorecido, ou ficam vazios quando o servidor disse `EVEN` — assim
    quem desenha não precisa conhecer a palavra do OP.GG.

    `build` é a leitura rica da mesma resposta, e é ``None`` quando ela
    não fecha (falta runa, falta feitiço, resposta recortada). Quem
    consome trata ``None`` como "siga com a build que já estava na
    tela": a do `opgg`, que não depende de saber o adversário.
    """

    my_champion: str
    opponent: str
    tip: str
    lane_advantage: str
    solo_kill_advantage: str
    play_style: str
    build: Build | None = None


def _options(raw: object, label: str) -> list[Block]:
    """As alternativas de um campo de item, cada uma como um bloco.

    Todo campo de item desta resposta tem a mesma forma — `ids`,
    `play`, `win`, `pick_rate` —, então uma leitura só serve para
    iniciais, botas, `single_items` e `last_items`. O que muda entre
    eles é o rótulo e onde entram na ordem de compra.
    """
    if not isinstance(raw, list):
        return []
    options: list[Block] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        ids = entry.get("ids")
        if not isinstance(ids, list) or not ids:
            continue
        try:
            items = tuple(int(item) for item in ids)
            play = int(entry.get("play") or 0)
            win = int(entry.get("win") or 0)
            pick_rate = float(entry.get("pick_rate") or 0.0)
        except (TypeError, ValueError):
            continue
        options.append(
            Block(
                label=label,
                items=items,
                win_rate=win / play if play else 0.0,
                games=play,
                pick_rate=pick_rate,
            )
        )
    return options


def _item_page(data: dict) -> tuple[Page, ...]:
    """A lista de compra inteira, do item inicial ao último.

    Uma página só, sem rótulo de critério: as alternativas vivem
    dentro de cada bloco, então não há uma segunda leitura para uma
    segunda aba oferecer.
    """
    blocks: list[Block] = []
    bought: set[int] = set()

    # Iniciais e botas entram na reserva como qualquer degrau: quem
    # escapa dela é o consumível, item a item, por
    # `buildblocks.CONSUMABLES`. Com a exceção antiga — o degrau
    # inteiro de fora — o item inicial permanente reaparecia no meio
    # dos lendários, mandando comprar dois.
    for field, label in (("starter_items", STARTER_LABEL), ("boots", BOOTS_LABEL)):
        block = slot(_options(data.get(field), label), bought)
        if block is not None:
            blocks.append(block)

    depths = data.get("single_items")
    if isinstance(depths, list):
        for entry in sorted(
            (item for item in depths if isinstance(item, dict)),
            key=lambda item: item.get("depth") or 0,
        ):
            label = DEPTH_LABELS.get(entry.get("depth") or 0)
            if label is None:
                continue
            block = slot(_options(entry.get("items"), label), bought)
            if block is not None:
                blocks.append(block)

    extra = extras(_options(data.get("last_items"), EXTRA_LABEL), bought, EXTRA_LABEL)
    if extra is not None:
        blocks.append(extra)

    if not blocks:
        return ()
    return (Page(label="", blocks=tuple(blocks)),)


def _page_perks(entry: dict) -> tuple[int, int, tuple[int, ...]] | None:
    """Uma entrada de `runes` virada no trio que o cliente instala.

    As nove runas saem na ordem que o LCU espera — as quatro da árvore
    primária, as duas da secundária e os três fragmentos —, que é a
    mesma em que o servidor as devolve. Qualquer campo faltando
    invalida a página inteira, e não a metade que faltou: página de
    runa incompleta entra na partida em silêncio e só aparece quando já
    é tarde.
    """
    try:
        style = int(entry.get("primary_page_id") or 0)
        sub_style = int(entry.get("secondary_page_id") or 0)
        primary = [int(rune) for rune in entry.get("primary_rune_ids") or []]
        secondary = [int(rune) for rune in entry.get("secondary_rune_ids") or []]
        shards = [int(rune) for rune in entry.get("stat_mod_ids") or []]
    except (TypeError, ValueError):
        return None
    perks = tuple(primary + secondary + shards)
    if not style or not sub_style or len(perks) != PERK_COUNT or 0 in perks:
        return None
    return style, sub_style, perks


def _rune_pages(data: dict) -> tuple[RunePage, ...]:
    """As páginas de runa que os dados sustentam, com o critério no nome.

    O servidor devolve as cinco combinações mais vistas do confronto, e
    aqui elas são **as observadas** — nenhuma é sintetizada. A tentação
    era montar a "melhor página possível" escolhendo o vencedor de cada
    encaixe em `single_runes`, que tem amostra bem maior (534 contra
    286). Não dá: `single_runes` agrega os encaixes de páginas com
    árvores primárias diferentes, então a lista de `primary_page` da
    Ahri traz Manaflow Band e Transcendence, que são de Feitiçaria.
    Sem a estrutura de árvore e de linha — que só existe no catálogo do
    cliente, em `core/perks.py` — juntar os líderes de cada encaixe
    produziria com facilidade uma página inválida: duas runas da mesma
    linha, ou runas de uma árvore que não é a escolhida. Página
    inválida é pior que página pobre.

    O critério de `ranking` costuma aprovar uma página só, e isso é
    resposta, não falha: as alternativas do confronto Ahri/Zed têm 39,
    28, 23 e 22 partidas. 60,9% em 23 partidas não é uma segunda build,
    é ruído com nome de recomendação.
    """
    raw = data.get("runes")
    if not isinstance(raw, list):
        return ()
    pages: list[RunePage] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        parsed = _page_perks(entry)
        if parsed is None:
            continue
        style, sub_style, perks = parsed
        try:
            play = int(entry.get("play") or 0)
            win = int(entry.get("win") or 0)
            pick_rate = float(entry.get("pick_rate") or 0.0)
        except (TypeError, ValueError):
            continue
        pages.append(
            RunePage(
                label="",
                style=style,
                sub_style=sub_style,
                perks=perks,
                win_rate=win / play if play else 0.0,
                games=play,
                pick_rate=pick_rate,
            )
        )
    if not pages:
        return ()

    def renomear(page: RunePage, label: str) -> RunePage:
        return RunePage(
            label=label,
            style=page.style,
            sub_style=page.sub_style,
            perks=page.perks,
            win_rate=page.win_rate,
            games=page.games,
            pick_rate=page.pick_rate,
        )

    most_played = max(pages, key=lambda page: page.games)
    best_rate = ranking.best(
        pages, lambda page: (page.win_rate, page.games, page.pick_rate)
    )
    if best_rate is None or best_rate.perks == most_played.perks:
        # Uma página só: rótulo de critério sugeriria uma segunda aba
        # que não existe.
        return (most_played,)
    return (
        renomear(most_played, MOST_PLAYED_LABEL),
        renomear(best_rate, BEST_RATE_LABEL),
    )


def _spells(data: dict) -> tuple[int, int] | None:
    """O par de feitiços mais jogado, ou ``None``.

    Feitiço não tem alternativa a oferecer: o cliente instala um par
    só, e trocar Flash por outra coisa com base em 3% de escolha seria
    mexer no que o jogador mais depende sem nada que sustente.
    """
    options = _options(data.get("summoner_spells"), "")
    if not options:
        return None
    chosen = max(options, key=lambda block: block.games)
    if len(chosen.items) != 2:
        return None
    return (chosen.items[0], chosen.items[1])


def _letters(order: object) -> tuple[str, ...]:
    """Uma sequência de habilidades, já validada.

    Vale o mesmo cuidado do `opgg`: a ordem vira letra na tela, e um
    valor estranho viraria um quadradinho vazio no meio da sequência em
    vez de um erro visível.
    """
    if not isinstance(order, list):
        return ()
    letters = tuple(str(letter).upper() for letter in order)
    if not letters or any(letter not in ("Q", "W", "E", "R") for letter in letters):
        return ()
    return letters


def _skills(data: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A ordem de habilidades mais jogada e a ordem de maximização."""
    order: tuple[str, ...] = ()
    raw = data.get("skills")
    if isinstance(raw, list):
        entries = [entry for entry in raw if isinstance(entry, dict)]
        if entries:
            best = max(entries, key=lambda entry: entry.get("play") or 0)
            order = _letters(best.get("order"))

    max_order: tuple[str, ...] = ()
    raw = data.get("skill_masteries")
    if isinstance(raw, list):
        entries = [entry for entry in raw if isinstance(entry, dict)]
        if entries:
            best = max(entries, key=lambda entry: entry.get("play") or 0)
            max_order = _letters(best.get("ids"))
    return order, max_order


def _stats(data: dict) -> Stats | None:
    """O boletim do campeão, quando a resposta trouxe o resumo."""
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return None
    average = summary.get("average_stats")
    if not isinstance(average, dict):
        return None
    try:
        return Stats(
            games=int(average.get("play") or 0),
            win_rate=float(average.get("win_rate") or 0.0),
            pick_rate=float(average.get("pick_rate") or 0.0),
            ban_rate=float(average.get("ban_rate") or 0.0),
            kda=float(average.get("kda") or 0.0),
            tier=int(average.get("tier") or 0),
            rank=int(average.get("rank") or 0),
        )
    except (TypeError, ValueError):
        return None


def parse_guide(data: dict) -> Build | None:
    """A build inteira do guia de confronto, ou ``None``.

    Tudo-ou-nada nas runas e nos feitiços, exatamente como em
    `opgg.parse_build` e pelo mesmo motivo: entrar em partida com três
    runas certas e o resto em branco é um estrago silencioso. Os itens
    seguem regra própria, mais frouxa — um degrau a menos na loja não
    estraga nada.

    O `Build` devolvido é o mesmo tipo que o `opgg` produz, de
    propósito. É o contrato que o `loadout`, a loja e a tela já falam;
    trocar a fonte da build não deve obrigar nenhum deles a saber que
    existem duas fontes.
    """
    pages = _rune_pages(data)
    spells = _spells(data)
    if not pages or spells is None:
        return None
    order, max_order = _skills(data)
    principal = pages[0]
    return Build(
        style=principal.style,
        sub_style=principal.sub_style,
        perks=principal.perks,
        spells=spells,
        pages=_item_page(data),
        rune_pages=pages,
        skill_order=order,
        skill_max=max_order,
        stats=_stats(data),
    )


def parse_matchup(payload: dict, mine: str, opponent: str) -> Matchup | None:
    """Lê a resposta do guia. ``None`` quando não há nada aproveitável.

    A régua era a dica escrita: sem ela, ``None``. Ficou estreita
    demais no dia em que esta resposta passou a trazer também a build —
    uma resposta sem dica mas com cinco páginas de runa e a lista de
    compra aberta por profundidade não é uma resposta vazia. Agora
    ``None`` significa o que diz: não veio dica **nem** build, e não há
    o que desenhar.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    tip = (data.get("opponent_champion_tip") or "").strip()
    build = parse_guide(data)
    if not tip and build is None:
        return None

    def favorito(campo: str) -> str:
        valor = (data.get(campo) or "").strip()
        return "" if valor.upper() == EVEN else valor

    estilo = (data.get("recommended_play_style") or "").strip()
    return Matchup(
        my_champion=mine,
        opponent=opponent,
        tip=tip,
        lane_advantage=favorito("lane_advantage_champion"),
        solo_kill_advantage=favorito("lane_solo_kill_advantage_champion"),
        play_style=PLAY_STYLES.get(estilo.lower(), estilo),
        build=build,
    )


def _send(arguments: dict) -> str:
    """Chama a ferramenta e devolve o texto da resposta.

    Mesma conversa JSON-RPC do `opgg`, inclusive o `text/event-stream`
    que o servidor às vezes escolhe. O timeout é mais folgado porque
    esta resposta é grande: o servidor ignora `desired_output_fields`
    nesta ferramenta e manda os 50 KB inteiros — que hoje são lidos
    quase por inteiro, e não mais só pela dica.
    """
    import json

    import requests

    from .opgg import ENDPOINT

    response = requests.post(
        ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": TOOL, "arguments": arguments},
        },
        timeout=15,
    )
    response.raise_for_status()

    body = response.text
    for line in body.splitlines():
        if line.startswith("data: "):
            body = line[6:]
            break
    payload = json.loads(body)
    content = (payload.get("result") or {}).get("content") or []
    return "".join(part.get("text", "") for part in content)


class MatchupSource:
    """Busca guias de confronto, lembrando o que já perguntou.

    O cache importa mais aqui do que na build: o usuário troca de
    adversário na tela para comparar, e voltar ao anterior não pode
    custar outra viagem de 50 KB.
    """

    def __init__(self, send: Callable[[dict], str] | None = None) -> None:
        self._send = send or _send
        self._cache: dict[tuple[str, str, str], Matchup] = {}

    def fetch(self, mine: str, opponent: str, position: str) -> Matchup | None:
        """O guia de `mine` contra `opponent` naquela rota, ou ``None``.

        Falha vira ``None`` como no resto da ponte com o OP.GG: isto é
        um extra sobre a build, e nada do que já está na tela depende
        de a consulta dar certo.
        """
        import json

        from .opgg import POSITIONS, champion_slug

        if not mine or not opponent:
            return None
        lane = POSITIONS.get((position or "").lower())
        if lane is None:
            return None

        key = (mine, opponent, lane)
        if key in self._cache:
            return self._cache[key]

        try:
            text = self._send(
                {
                    # O nome vai em forma de slug: ver `champion_slug`.
                    # Os nomes de exibição seguem para `parse_matchup`,
                    # que é quem os escreve na tela.
                    "my_champion": champion_slug(mine),
                    "opponent_champion": champion_slug(opponent),
                    "position": lane,
                    # Ver o cabeçalho: em pt_BR esta ferramenta responde
                    # vazio, sem erro nenhum para avisar.
                    "lang": "en_US",
                }
            )
            payload = json.loads(text or "{}")
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None
        found = parse_matchup(payload, mine, opponent)
        if found is not None:
            self._cache[key] = found
        return found

    def fetch_build(
        self,
        mine: str,
        opponent: str,
        position: str,
        fallback=None,
        aram: bool = False,
        tier: str | None = None,
    ) -> tuple[Build | None, str]:
        """A build do confronto quando dá, a do campeão quando não dá.

        Devolve o par ``(build, oponente)``. O segundo elemento é o
        adversário cujo guia produziu a build, e vem vazio quando quem
        respondeu foi o boletim do campeão — é assim que a tela sabe
        se pode escrever "contra Zed" no cabeçalho sem mentir.

        A rede existe porque `lol_get_lane_matchup_guide` **exige**
        `opponent_champion`: não há curinga, não há "qualquer um". Sem
        adversário travado — e ele passa a maior parte da seleção sem
        estar travado — a pergunta não pode nem ser feita. Sem esta
        queda para `lol_get_champion_analysis` a tela ficaria vazia
        justamente no caso mais comum, que é o pior lugar possível
        para um recurso novo cobrar o preço de existir.

        A queda também cobre o confronto que o OP.GG conhece mas não
        tem amostra para descrever: guia que volta sem página de runa
        aprovada devolve ``None`` no `parse_guide`, e aí o boletim do
        campeão é melhor do que nada pelo mesmo motivo.
        """
        found = self.fetch(mine, opponent, position)
        if found is not None and found.build is not None:
            return found.build, opponent

        if fallback is None:
            return None, ""
        try:
            return (
                fallback.fetch(
                    mine,
                    position,
                    aram,
                    **({"tier": tier} if tier else {}),
                ),
                "",
            )
        except Exception:
            # Mesma regra do resto da ponte: a fonte externa é um
            # extra, e a recomendação da Riot ainda vem depois dela.
            return None, ""
