"""Feitiços e runas a partir da recomendação da Riot.

O cliente já sabe o que é bom para cada campeão em cada rota — é o que
ele mostra na seleção de campeões, e sai por
`/lol-perks/v1/recommended-pages`. Uma chamada devolve as runas e os
feitiços de uma vez, então não há nada para o usuário configurar aqui
além de ligar ou desligar.

O que este módulo cuida de não estragar:

- **o lado do Flash.** A recomendação vem numa ordem qualquer, e trocar
  a tecla do Flash minutos antes da partida custa mais do que qualquer
  runa devolve.
- **as páginas de runas do usuário.** O app mantém uma página só, a
  dele, reconhecida pelo nome. Sem espaço para criá-la, ele desiste e
  avisa; apagar página alheia para abrir vaga está fora de questão.

Quando há uma fonte externa ligada — o OP.GG —, ela fala primeiro: o
que venceu em partidas de verdade costuma valer mais que a curadoria
da Riot. Mas ela responde em segundos, e a seleção de campeões não
espera por ninguém, então a consulta corre numa thread à parte e o
resultado é recolhido num tick seguinte. Passou do teto de espera, a
Riot assume.

O mesmo OP.GG responde builds diferentes conforme o elo consultado, e
essa é a única variedade que dá para oferecer sem inventar nada. Com as
opções ligadas, alguns elos fixos de comparação são perguntados também
e a tela mostra o que voltou de verdade — elo que não responde não vira
botão. Essas consultas correm numa thread só delas, fora do teto de
espera: somadas passam dos oito segundos, e presas ao mesmo orçamento
derrubariam runas e arsenal para a reserva da Riot em toda seleção.
Chegando tarde elas ainda valem, porque a seleção dura minutos. O que é
aplicado sozinho continua saindo do elo dos Ajustes: clicar numa opção
é escolha do usuário, não requisito para entrar em partida com runa.

Erros aqui não sobem: se a recomendação falhar, a seleção e o
banimento automáticos seguem sem saber de nada. A exceção é o cliente
ter fechado — aí não há partida a atrapalhar, e é o watcher quem
precisa da notícia para reconectar.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Sequence

from ..config import DEFAULT_FLASH_KEY, OPGG_TIERS, Config
from ..lcu import endpoints
from ..lcu.client import ClientClosed, LcuError
from .itemsets import ItemSets
from .opgg import Build, Page

#: Prefixo do nome da página que o app cria. É por ele que a página é
#: reconhecida depois — e é o que separa a nossa das do usuário.
PAGE_PREFIX = "LoL Queue"

#: Mapa padrão quando o cliente não diz qual é: a Fenda.
DEFAULT_MAP = 11

#: Mapa do Abismo dos Lamentos. Runa e feitiço de ARAM são outros.
ARAM_MAP = 12

#: Quanto se espera pela fonte externa antes de chamar a Riot. Medido:
#: as respostas chegam entre três e seis segundos, então o teto dá
#: folga sem chegar perto do fim da seleção.
WAIT_SECONDS = 8.0

#: Sinal interno de "ainda não sei" — diferente de "não veio nada".
PENDING = object()

#: Quantas vezes reenviar os feitiços antes de desistir, e quanto
#: esperar entre uma tentativa e a seguinte. O PATCH da seleção
#: responde 2xx sem surtir efeito — a mesma mentira que já custou um
#: banimento em `champ_select` —, então quem confirma é a releitura da
#: sessão no tick seguinte, não a resposta.
MAX_SPELL_ATTEMPTS = 4
SPELL_RETRY_SECONDS = 1.5

#: De quanto em quanto tempo se confere se a página que o app gravou
#: ainda é a página ativa, e quantas vezes se insiste em pô-la de volta
#: antes de desistir. O cliente troca a página ativa sozinho no fim da
#: seleção — medido: gravada às 08:05:34, trocada pela recomendação
#: dele às 08:07:18, quase dois minutos depois do lock —, então conferir
#: uma vez na hora de gravar não prova nada sobre o que entra na
#: partida. O teto existe para o app não brigar em laço com um cliente
#: que insista: três recolocações e ele conta o que houve e para.
PAGE_CHECK_SECONDS = 2.0
MAX_PAGE_FIXES = 3

#: Elos consultados para as opções de runa: três pontos bem separados
#: da escala, fixos de propósito. Não é o elo dos Ajustes — aquele
#: decide o que é aplicado sozinho, este é o leque que a tela oferece
#: para comparar.
RUNE_OPTION_TIERS = ("diamond_plus", "master", "challenger")

#: Como o confronto se apresenta: no rótulo da aba do arsenal e na
#: chave da opção de runa. O prefixo é o que separa uma coisa da
#: outra dentro de `_options`, onde todas as outras chaves são elos.
MATCHUP_PREFIX = "vs "

#: De onde veio a recomendação, para o registro dizer. Sem isso não
#: dá para perceber que o OP.GG parou de responder e que o app está
#: rodando na reserva há semanas.
ORIGIN_RIOT = "Riot"
ORIGIN_OPGG = "OP.GG"

#: O Flash. É o único feitiço cuja tecla o jogador decora, e o
#: único que o app tem motivo para fixar de um lado.
FLASH_SPELL_ID = 4

#: Qual campo do cliente é qual tecla. `spell1Id` é o D e `spell2Id`
#: é o F na ligação padrão do jogo — é o que o cliente mostra e o
#: que a esmagadora maioria usa.
FLASH_SLOTS = ("d", "f")


def align_spells(
    recommended: Sequence[int],
    current: Iterable[int | None],
    flash_key: str = DEFAULT_FLASH_KEY,
) -> tuple[int, int]:
    """Põe a dupla recomendada na ordem que o jogador já usa.

    Com uma tecla escolhida nos Ajustes, o Flash vai para ela e ponto.
    Isso existe porque o app é usado em conta emprestada: o dono tem o
    Flash no lado dele, o app copia esse lado, e quem está jogando
    aperta a tecla errada na hora que menos podia.

    Sem escolha — o padrão —, vale o que o jogador já tem na tela: se
    algum feitiço aparece nos dois pares em lados trocados, a dupla
    inteira é invertida. Como só existem dois lados, um feitiço em
    comum já decide a ordem dos dois.
    """
    first, second = recommended[0], recommended[1]
    if flash_key in FLASH_SLOTS and FLASH_SPELL_ID in (first, second):
        other = second if first == FLASH_SPELL_ID else first
        if flash_key == "d":
            return FLASH_SPELL_ID, other
        return other, FLASH_SPELL_ID
    mine = list(current)
    if first in mine[1:] or second in mine[:1]:
        return second, first
    return first, second


def local_champion(session: dict) -> int:
    """Campeão travado pelo jogador local, ou 0 enquanto não houver.

    Fica em zero durante o hover: o cliente só preenche `championId`
    depois da trava. É de propósito que o equipamento espere por isso —
    aplicar runa em campeão que ainda pode mudar seria trabalho jogado
    fora, e visível para o usuário.
    """
    cell_id = session.get("localPlayerCellId")
    for member in session.get("myTeam") or []:
        if member.get("cellId") == cell_id:
            champion_id = member.get("championId")
            return champion_id if isinstance(champion_id, int) else 0
    return 0


def local_spells(session: dict) -> tuple[int | None, int | None]:
    """Feitiços que o jogador local tem escolhidos agora."""
    cell_id = session.get("localPlayerCellId")
    for member in session.get("myTeam") or []:
        if member.get("cellId") == cell_id:
            return member.get("spell1Id"), member.get("spell2Id")
    return None, None


def rune_options(found: Sequence[tuple[str, Build]]) -> dict[str, Build]:
    """Uma opção por página distinta, na ordem em que os elos vieram.

    Dois elos que devolvem exatamente a mesma página viram um botão só:
    dois idênticos lado a lado só ocupariam espaço. Qualquer diferença
    de árvore ou de runa continua sendo uma opção própria — esconder o
    que é diferente seria pior do que repetir.
    """
    seen: dict[tuple, tuple[str, Build]] = {}
    for tier, build in found:
        seen.setdefault((build.style, build.sub_style, build.perks), (tier, build))
    return {tier: build for tier, build in seen.values()}


def option_label(key: str) -> str:
    """Como a opção de runa se lê no registro: o elo, ou o confronto."""
    if key.startswith(MATCHUP_PREFIX):
        return f"do confronto contra {key[len(MATCHUP_PREFIX):]}"
    return f"de {OPGG_TIERS.get(key, key)}"


def same_page(current, watch) -> bool:
    """A página ativa no cliente é a que o app gravou?

    Comparar o `id` bastaria se o cliente sempre gravasse o que
    recebeu, e ele nem sempre grava: um perk fora da árvore some do
    corpo sem que o POST reclame. Então o conteúdo entra na conta —
    mas só o que foi pedido de verdade, para uma recomendação sem
    árvore declarada não virar divergência eterna.
    """
    if not isinstance(current, dict) or current.get("id") != watch.page_id:
        return False
    for campo, esperado in (
        ("primaryStyleId", watch.style),
        ("subStyleId", watch.sub_style),
    ):
        if esperado is not None and current.get(campo) != esperado:
            return False
    if not watch.perks:
        return True
    perks = tuple(
        perk
        for perk in current.get("selectedPerkIds") or []
        if isinstance(perk, int)
    )
    return perks == watch.perks


def replaceable(current) -> bool:
    """Se dá para pôr a página do app de volta sem passar por cima do jogador.

    Sem página ativa, volta. Página temporária, volta: é a gaveta das
    recomendações do cliente, onde jogador nenhum grava. Outra página
    nossa, volta. Permanente com nome alheio é escolha feita à mão na
    tela de runas, e essa ganha.
    """
    if not isinstance(current, dict):
        return True
    if current.get("isTemporary"):
        return True
    name = current.get("name")
    return isinstance(name, str) and name.startswith(f"{PAGE_PREFIX}: ")


def versus_pages(pages: Sequence[Page], opponent: str) -> tuple[Page, ...]:
    """As páginas do guia rotuladas pelo adversário que as produziu.

    O rótulo vai para o título do conjunto na loja, e é ele que diz ao
    jogador qual aba é qual durante a partida. Página que já tem nome
    próprio o mantém depois do adversário; a maioria vem sem, porque o
    guia de confronto traz uma leitura só.
    """
    return tuple(
        replace(
            page,
            label=(
                f"{MATCHUP_PREFIX}{opponent} — {page.label}"
                if page.label
                else f"{MATCHUP_PREFIX}{opponent}"
            ),
        )
        for page in pages
    )


@dataclass
class _Search:
    """Uma consulta à fonte externa que ainda está no ar."""

    champion_id: int
    started: float
    position: str
    aram: bool
    thread: threading.Thread | None = None
    result: Build | None = None


@dataclass
class _Watch:
    """A página que o app gravou, e o bastante para gravá-la de novo."""

    page_id: int
    name: str
    style: int | None
    sub_style: int | None
    perks: tuple[int, ...]


class Loadout:
    """Aplica feitiços e runas quando o campeão fica definido."""

    def __init__(
        self,
        client,
        config: Config,
        catalog,
        log: Callable[[str], None] | None = None,
        source=None,
        now: Callable[[], float] | None = None,
        on_rune_options: Callable[
            [list[str], str | None, dict[str, Build]], None
        ]
        | None = None,
        on_analysis: Callable[[int, str, Build | None, str], None] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._catalog = catalog
        self._log = log or (lambda message: None)
        self._source = source
        self._now = now or time.monotonic
        self._items = ItemSets(client, log=self._log)
        # A última reclamação sobre a página de runas. `apply` roda a
        # cada tick da seleção, e sem isto a mesma frase saía onze
        # vezes em noventa segundos, enterrando o resto do diário.
        self._complaint = ""
        self._done_for: int | None = None
        self._pending: _Search | None = None
        # Se a resposta principal passar do teto, as runas podem seguir
        # pela Riot, mas a consulta não deve ser jogada fora. Quando ela
        # finalmente voltar ainda há tempo para atualizar a Análise e o
        # arsenal durante a seleção.
        self._late: _Search | None = None
        self._external_status = "no_data"
        self._analysis_report: tuple[int, str, int] | None = None
        # Avisa a tela quais builds de runa existem e qual está no
        # cliente agora. Mesmo formato do resto da ponte com a UI: um
        # callback simples, que do outro lado é o `emit` de um sinal Qt.
        self._on_rune_options = on_rune_options
        # Entrega à tela a build inteira do campeão travado — não para
        # aplicar, para ler. Ordem de habilidade, confrontos e o boletim
        # do campeão vêm de carona na mesma resposta que já buscamos
        # para runas e itens, então isto não custa uma consulta a mais.
        self._on_analysis = on_analysis
        self._options: dict[str, Build] = {}
        self._active_tier: str | None = None
        # Os elos de comparação correm na sua própria thread, fora do
        # teto de espera da build principal. A geração diz de qual
        # seleção a busca é: resposta de uma seleção anterior é largada.
        self._options_thread: threading.Thread | None = None
        self._options_gen = 0
        # Bilhete deixado pelo clique na tela, lido no tick seguinte.
        self._requested_tier: str | None = None
        # O mesmo acordo para o adversário escolhido na tela: o guia
        # chega pronto da thread da janela e é instalado no tick, que é
        # quem tem o direito de falar com o cliente.
        self._requested_matchup: tuple[str, Build] | None = None
        # O arsenal do campeão, guardado porque a loja só aceita a lista
        # inteira: gravar a página do confronto sozinha apagaria a
        # leitura geral que já estava lá.
        self._pages: tuple[Page, ...] = ()
        # Se a tela chegou a receber alguma opção. Sem isso o "não há
        # nada a mostrar" seria repetido a cada seleção que não tem.
        self._published = False
        # A dupla de feitiços pedida ao cliente e ainda não confirmada.
        # Enquanto ela existir, todo tick relê a sessão e insiste.
        self._spells_wanted: tuple[int, int] | None = None
        self._spells_at = 0.0
        self._spell_attempts = 0
        self._spells_origin = ORIGIN_RIOT
        # A página que o app gravou, para conferir a cada tick se ela
        # continua sendo a ativa. Guardado o conteúdo inteiro porque
        # recolocar pode significar criar de novo: o cliente às vezes
        # apaga a nossa antes de pôr a dele.
        self._page_watch: _Watch | None = None
        self._page_checked_at = 0.0
        self._page_fixes = 0

    def reset(self) -> None:
        self._done_for = None
        self._complaint = ""
        self._pages = ()
        self._requested_matchup = None
        # A thread em voo, se houver, é daemon e some sozinha; o que
        # importa é não colar a resposta de uma seleção na seguinte.
        self._pending = None
        self._late = None
        self._analysis_report = None
        self._spells_wanted = None
        self._spell_attempts = 0
        self._page_watch = None
        self._page_checked_at = 0.0
        self._page_fixes = 0
        self._clear_options()

    def request_rune_option(self, tier: str) -> None:
        """Pede a troca para a build de runa de outro elo.

        Chamado pela thread da GUI, no clique. Não fala com o cliente
        aqui de propósito: guarda o pedido e deixa o tick seguinte
        executá-lo, na thread que é dona das chamadas à LCU — o mesmo
        acordo que o interruptor do motor já segue.
        """
        self._requested_tier = tier

    def request_matchup(self, opponent: str, matchup) -> None:
        """Guarda o guia do confronto que a tela acabou de buscar.

        Chamado pela thread da GUI, quando o jogador escolhe contra
        quem está na rota. A busca já aconteceu lá — o que passa por
        aqui é o resultado —, e a instalação fica para o tick seguinte
        pelo mesmo motivo do clique de runa: quem fala com o cliente é
        a thread da seleção.

        Guia sem build — confronto que o OP.GG conhece mas não tem
        amostra para descrever — não vira bilhete: não há o que
        instalar, e limpar o pedido evita que o tick tropece nele.
        """
        build = getattr(matchup, "build", None)
        if not opponent or build is None:
            self._requested_matchup = None
            return
        self._requested_matchup = (opponent, build)

    def apply(self, session: dict) -> None:
        if not (
            self._config.auto_spells
            or self._config.auto_runes
            or self._config.auto_items
        ):
            return
        champion_id = local_champion(session)
        # Antes de qualquer outra coisa, e nos dois caminhos: a troca
        # de feitiço só é verdade quando a sessão devolve a dupla nova,
        # e a sessão só é relida aqui.
        self._settle_spells(session)
        if champion_id <= 0:
            return
        if champion_id == self._done_for:
            # Já equipado — o que não quer dizer que continue equipado.
            # A conferência vem antes dos cliques porque é ela que
            # decide o que entra na partida.
            self._collect_late_external(champion_id, session)
            self._guard_page()
            self._serve_matchup(champion_id)
            self._serve_choice(champion_id)
            return

        external = self._external(champion_id, session)
        if external is PENDING:
            # A fonte externa ainda está respondendo. Sair sem marcar
            # é o que faz o próximo tick voltar aqui para recolher.
            if self._external_status == "awaiting_route":
                self._announce_analysis(
                    champion_id, session, None, self._external_status
                )
            return

        # Marcado antes de agir: uma falha no meio do caminho não pode
        # virar uma tentativa por tick pelo resto da seleção.
        self._done_for = champion_id

        # Antes de equipar, e fora do bloco protegido, porque a leitura
        # não fala com o cliente: mesmo que aplicar runa falhe adiante,
        # o que já sabemos sobre o campeão vale para ser mostrado.
        self._announce_analysis(
            champion_id, session, external, self._external_status
        )

        try:
            # O arsenal vem primeiro porque nao depende da Riot: se a
            # recomendacao dela faltar, ele ainda tem por que existir.
            if self._config.auto_items and external is not None:
                self._apply_arsenal(champion_id, external)
            elif self._config.auto_items:
                self._report_missing_arsenal(self._external_status)
            if not (self._config.auto_spells or self._config.auto_runes):
                return
            recommendation = self._recommendation(
                champion_id, session, external
            )
            if recommendation is None:
                return
            origem = ORIGIN_OPGG if external is not None else ORIGIN_RIOT
            if self._config.auto_spells:
                self._apply_spells(recommendation, session, origem)
            if self._config.auto_runes and self._apply_runes(
                recommendation, champion_id, origem
            ):
                # Só o que veio do OP.GG tem elo; a reserva da Riot não
                # é uma das opções e não pode aparecer marcada como tal.
                self._active_tier = (
                    self._config.opgg_tier if external is not None else None
                )
            self._publish_options()
        except ClientClosed:
            # Cliente fechado não é falha de runa: é o watcher que tem de
            # saber, para reconectar. Engolir aqui trocaria o “Cliente do
            # LoL fechado.” por um erro de runa enganoso — a mesma regra
            # que o motor já segue.
            raise
        except LcuError as exc:
            self._log(f"Não deu para aplicar runas e feitiços: {exc}")

    def _announce_analysis(
        self, champion_id: int, session: dict, build: Build | None, status: str
    ) -> None:
        """Publica a leitura e o motivo de ela ainda não existir.

        O estado de rota pendente pode aparecer a cada tick.  Deduplicar aqui
        evita atravessar a ponte Qt quatro vezes por segundo com a mesma frase,
        sem esconder uma build que chegou depois.
        """
        if self._on_analysis is None:
            return
        marker = (champion_id, status, id(build))
        if marker == self._analysis_report:
            return
        self._analysis_report = marker
        # Import tardio como os outros usos aqui: `champ_select` importa
        # este módulo, e no topo isto fecharia o ciclo.
        from .champ_select import local_position

        self._on_analysis(champion_id, local_position(session), build, status)

    def _apply_arsenal(self, champion_id: int, build: Build) -> None:
        """Monta a loja sem duplicar o caminho da resposta tardia."""
        # Guardado para o confronto: escolhido o adversário, a loja recebe
        # as duas leituras juntas, e sem isto a do campeão sumiria na segunda
        # gravação.
        self._pages = tuple(build.pages)
        if not self._pages:
            self._log("Arsenal não foi montado: o OP.GG devolveu uma build sem itens.")
            return
        self._items.apply(
            champion_id,
            self._catalog.name(champion_id),
            self._pages,
            self._map_id(),
        )

    def _report_missing_arsenal(self, status: str) -> None:
        """Deixa no diário o motivo real de não haver itens na loja."""
        if status == "timed_out":
            self._log(
                "Arsenal aguardando o OP.GG: a resposta tardia ainda será "
                "aproveitada nesta seleção."
            )
        elif status == "awaiting_route":
            self._log("Arsenal aguardando a rota confirmada pelo cliente do LoL.")
        else:
            self._log(
                "Arsenal não foi montado: o OP.GG não devolveu uma build "
                "para esta combinação agora."
            )

    def _collect_late_external(self, champion_id: int, session: dict) -> None:
        """Aproveita uma resposta que chegou após a reserva da Riot.

        O teto protege pick e ban, mas descartar a resposta definitivamente
        fazia Análise e Arsenal falharem em conexões apenas um pouco mais
        lentas.  Runas e feitiços continuam na reserva nesta seleção; só os
        dados que podem entrar tarde sem atrapalhar o jogador são aplicados.
        """
        search = self._late
        if search is None or search.champion_id != champion_id:
            return
        if search.thread is not None and search.thread.is_alive():
            return
        self._late = None
        build = search.result
        status = "ready" if build is not None else "no_data"
        self._announce_analysis(champion_id, session, build, status)
        if build is None:
            if self._config.auto_items:
                self._report_missing_arsenal(status)
            return
        if not self._config.auto_items:
            return
        try:
            self._apply_arsenal(champion_id, build)
        except ClientClosed:
            raise
        except LcuError as exc:
            self._log(f"Não deu para montar o arsenal após a espera: {exc}")

    # ---------- recomendação ----------

    def _recommendation(
        self, champion_id: int, session: dict, external: Build | None
    ) -> dict | None:
        """A do OP.GG quando existe, a da Riot quando não.

        As duas saem daqui no mesmo formato — o da Riot — para que o
        resto do módulo não precise saber de onde veio.
        """
        if external is not None:
            return {
                "primaryPerkStyleId": external.style,
                "secondaryPerkStyleId": external.sub_style,
                "summonerSpellIds": list(external.spells),
                "perks": [{"id": perk} for perk in external.perks],
            }
        return self._riot_recommendation(champion_id, session)

    def _riot_recommendation(self, champion_id: int, session: dict) -> dict | None:
        from .champ_select import local_position

        position = local_position(session).upper() or "NONE"
        payload = self._client.get(
            endpoints.PERK_RECOMMENDED.format(
                champion_id=champion_id,
                position=position,
                map_id=self._map_id(),
            )
        )
        if not isinstance(payload, list) or not payload:
            self._log(
                f"A Riot não recomendou nada para {self._catalog.name(champion_id)}."
            )
            return None
        return payload[0]

    # ---------- fonte externa ----------

    def _external(self, champion_id: int, session: dict):
        """A recomendação do OP.GG, ``PENDING`` ou ``None``.

        Nunca bloqueia. O tick da seleção roda a cada 0,25 s e é o
        mesmo que trava campeão e bane — parar aqui por segundos
        seria trocar a runa pela partida.
        """
        if self._source is None:
            self._external_status = "no_data"
            return None

        from .champ_select import local_position

        position = local_position(session)
        aram = self._map_id() == ARAM_MAP
        # Na Fenda o OP.GG não aceita uma rota em branco. Em vez de
        # perguntar qualquer uma e colar uma build errada, esperamos a
        # informação real do cliente. A seleção ainda não acabou, então
        # isto não custa a recomendação inteira.
        if not aram and not position:
            self._external_status = "awaiting_route"
            return PENDING

        search = self._pending
        if search is None or search.champion_id != champion_id:
            # Trocar de campeão na mesma seleção torna a resposta tardia
            # anterior irrelevante; ela não pode ganhar uma segunda chance
            # de montar itens para quem o jogador não vai usar.
            if self._late is not None and self._late.champion_id != champion_id:
                self._late = None
            search = self._start(champion_id, position, aram)

        if search.thread is not None and search.thread.is_alive():
            if self._now() - search.started < WAIT_SECONDS:
                return PENDING
            # Runas e feitiços precisam seguir agora, mas Análise e
            # Arsenal ainda podem aproveitar o resultado se ele chegar na
            # sequência. Antes este objeto era perdido aqui para sempre.
            self._pending = None
            self._late = search
            self._external_status = "timed_out"
            self._log("O OP.GG demorou; usando a recomendação da Riot.")
            return None

        self._pending = None
        self._external_status = "ready" if search.result is not None else "no_data"
        return search.result

    def _start(self, champion_id: int, position: str, aram: bool) -> _Search:
        # O alias, não o nome: o cliente traduz o nome, e quem está
        # do outro lado só conhece o identificador da Riot.
        champion = self._catalog.alias(champion_id)
        search = _Search(
            champion_id=champion_id,
            started=self._now(),
            position=position,
            aram=aram,
        )
        # Campeão trocado depois da trava recomeça tudo: as opções da
        # busca anterior são de outro boneco e não podem ficar na tela.
        self._clear_options()
        gen = self._options_gen

        def run() -> None:
            try:
                search.result = self._source.fetch(
                    champion, position, aram, tier=self._config.opgg_tier
                )
            except Exception:
                # A fonte é um extra; quebrar aqui não pode custar a
                # recomendação da Riot, que ainda vem depois.
                search.result = None
            if self._config.auto_runes and self._config.auto_runes_options:
                self._start_options(gen, search.result, champion, position, aram)

        search.thread = threading.Thread(target=run, daemon=True)
        search.thread.start()
        self._pending = search
        return search

    def _start_options(
        self, gen: int, main: Build | None, champion: str, position: str, aram: bool
    ) -> None:
        """Busca as builds dos elos de comparação numa thread só delas.

        Fora do teto de espera de propósito, e essa é a diferença que
        importa: são três consultas de três a seis segundos cada, e
        somadas passam dos oito. Presas ao mesmo orçamento, ligar as
        opções derrubaria runas e arsenal para a reserva da Riot em toda
        seleção — quebrando duas coisas que funcionavam para oferecer
        uma terceira. Chegando tarde elas ainda valem: a seleção dura
        minutos e o botão está lá para ser clicado quando aparecer.

        Roda depois da build principal e nunca no lugar dela: o que é
        aplicado sozinho continua saindo do elo dos Ajustes. Elo que não
        responde simplesmente não vira opção — repetir a build de outro
        para encher a tela seria inventar dado.
        """

        def run() -> None:
            found: list[tuple[str, Build]] = []
            for tier in RUNE_OPTION_TIERS:
                if tier == self._config.opgg_tier:
                    # Já perguntado na busca principal; a fonte guardaria
                    # a resposta, mas não custa não depender disso.
                    build = main
                else:
                    try:
                        build = self._source.fetch(
                            champion, position, aram, tier=tier
                        )
                    except Exception:
                        build = None
                if self._options_gen != gen:
                    # Outra seleção começou enquanto isto corria.
                    return
                if build is not None:
                    found.append((tier, build))
            if not found:
                return
            self._options = rune_options(found)
            self._publish_options()

        thread = threading.Thread(target=run, daemon=True)
        self._options_thread = thread
        thread.start()

    def _map_id(self) -> int:
        """Fenda ou Abismo. A recomendação muda entre os dois.

        Uma falha aqui não pode subir. Este é o primeiro passo da
        busca externa, que corre fora do bloco protegido do `apply`,
        e quem chama `apply` é o mesmo tick que escolhe e bane
        campeão — a runa não tem o direito de atrapalhar isso.

        A exceção é o cliente ter fechado: aí não há mapa a adivinhar,
        e quem precisa saber é o watcher, para reconectar.
        """
        try:
            session = self._client.get(endpoints.GAMEFLOW_SESSION)
        except ClientClosed:
            raise
        except LcuError:
            return DEFAULT_MAP
        if isinstance(session, dict):
            map_id = (session.get("map") or {}).get("id")
            if isinstance(map_id, int):
                return map_id
        return DEFAULT_MAP

    # ---------- feitiços ----------

    def _apply_spells(
        self, recommendation: dict, session: dict, origem: str
    ) -> None:
        spells = recommendation.get("summonerSpellIds")
        if not isinstance(spells, list) or len(spells) < 2:
            return
        current = local_spells(session)
        first, second = align_spells(spells, current, self._config.flash_key)
        if (first, second) == current:
            return
        self._spells_origin = origem
        self._spell_attempts = 0
        self._send_spells(first, second)

    def _send_spells(self, first: int, second: int) -> None:
        """Pede a dupla. Nada é anunciado aqui — ver `_settle_spells`."""
        self._client.patch(
            endpoints.CHAMP_SELECT_MY_SELECTION,
            json={"spell1Id": first, "spell2Id": second},
        )
        self._spells_wanted = (first, second)
        self._spells_at = self._now()
        self._spell_attempts += 1

    def _settle_spells(self, session: dict) -> None:
        """Relê a sessão: ou pegou, ou insiste, ou conta que não deu.

        O único jeito de saber se o feitiço trocou é olhar de novo para
        a sessão. Anunciar em cima da resposta do PATCH era anunciar
        que o cliente ouviu, não que ele obedeceu: em três seleções
        seguidas o diário disse "feitiços aplicados" com a dupla errada
        na tela até o jogo começar.

        E a insistência precisa de uma porta própria porque `apply`
        marca `_done_for` antes de agir: sem isto a troca tem uma
        tentativa só na seleção inteira, e ela é justamente a que cai
        no cliente ainda ocupado abrindo a seleção.
        """
        wanted = self._spells_wanted
        if wanted is None:
            return
        if local_spells(session) == wanted:
            self._spells_wanted = None
            self._log(f"Feitiços do {self._spells_origin} aplicados.")
            return
        if self._now() - self._spells_at < SPELL_RETRY_SECONDS:
            return
        if self._spell_attempts >= MAX_SPELL_ATTEMPTS:
            self._spells_wanted = None
            self._complain(
                "Não consegui trocar os feitiços de invocador — o cliente "
                "recusou. Troque à mão antes de travar."
            )
            return
        try:
            self._send_spells(*wanted)
        except ClientClosed:
            raise
        except LcuError:
            # Recusa explícita não vira teimosia: o resto da seleção
            # segue, e o campeão e as runas não pagam por isto.
            self._spells_wanted = None

    # ---------- runas ----------

    def _apply_runes(
        self, recommendation: dict, champion_id: int, origem: str
    ) -> bool:
        name = self._install_page(
            champion_id,
            recommendation.get("primaryPerkStyleId"),
            recommendation.get("secondaryPerkStyleId"),
            [perk.get("id") for perk in recommendation.get("perks") or []],
        )
        if name is None:
            return False
        self._log(f"Runas do {origem} aplicadas — página “{name}”.")
        return True

    def _install_page(
        self, champion_id: int, style, sub_style, perks: Sequence[int]
    ) -> str | None:
        """Grava a página no cliente e a ativa. Devolve o nome, ou None.

        Dois caminhos chegam aqui: o automático, quando o campeão trava,
        e a troca que o usuário pediu na tela. Os dois reaproveitam a
        vaga da nossa página em vez de ir enchendo o cliente — mas só
        depois de haver substituta.

        A ordem é a parte que importa. Apagar primeiro era deixar o
        jogador sem página nenhuma sempre que o cliente recusasse o
        POST seguinte, o que na seleção significa entrar em partida sem
        runa. Criando antes, uma recusa não custa nada: a página de
        antes continua onde estava, ativa. A única hora em que se apaga
        primeiro é quando o cliente diz não haver vaga — aí abrir espaço
        é o que falta, e a página aberta é a nossa.

        E o "diz" é literal: `canAddCustomPage` é palpite do cliente,
        não fato. Numa conta com três vagas e as três ocupadas ele
        respondeu que dava para criar; e numa seleção inteira ele
        respondeu que não dava com uma página nossa parada ali, à
        espera de ser reaproveitada. Por isso a bandeira só decide se
        vale a pena abrir espaço antes — quem tem a palavra final é o
        POST. Tentar e ouvir a recusa custa uma chamada; acreditar na
        bandeira custou ao jogador entrar em partida sem runa, onze
        vezes seguidas, com o diário repetindo que a culpa era dele.
        """
        return self._write_page(
            f"{PAGE_PREFIX}: {self._catalog.name(champion_id)}",
            style,
            sub_style,
            perks,
        )

    def _write_page(
        self, name: str, style, sub_style, perks: Sequence[int]
    ) -> str | None:
        """Cria, ativa, confere e só então diz que deu certo."""
        page = self._create_page(
            {
                "name": name,
                "primaryStyleId": style,
                "subStyleId": sub_style,
                "selectedPerkIds": list(perks),
            }
        )
        page_id = page.get("id") if isinstance(page, dict) else None
        if page_id is None:
            self._complain("O cliente não devolveu a página de runas criada.")
            return None
        watch = _Watch(
            page_id=page_id,
            name=name,
            style=style,
            sub_style=sub_style,
            perks=tuple(perk for perk in perks if isinstance(perk, int)),
        )
        if not self._activate(watch):
            self._complain(
                "O cliente não ficou com a página de runas do app — "
                "confira a runa antes de a partida começar."
            )
            return None
        # Só depois de haver página ativa confirmada é que a de antes
        # perde a vaga: uma limpeza feita mais cedo deixaria o jogador
        # sem página nenhuma toda vez que a ativação falhasse.
        self._discard_old_pages(keep=page_id)
        self._page_watch = watch
        self._page_checked_at = self._now()
        return name

    def _activate(self, watch: _Watch) -> bool:
        """Ativa a página e relê para saber se pegou.

        Criar não ativa, e ativar não garante: `PUT /currentpage`
        responde 2xx e às vezes não muda nada — a mesma mentira que o
        PATCH dos feitiços já contava. Sem esta releitura o diário
        anunciava “Runas aplicadas” enquanto a partida carregava outra
        página, e foi assim por seleções inteiras sem ninguém saber.

        Duas tentativas porque a primeira cai no cliente ainda ocupado
        montando a seleção; da terceira em diante quem insiste é a
        conferência por tick, que tem tempo do lado dela.
        """
        for _ in range(2):
            self._client.put(endpoints.PERK_CURRENT_PAGE, json=watch.page_id)
            if self._is_current(watch):
                return True
        return False

    def _is_current(self, watch: _Watch) -> bool:
        """Se a página ativa é a nossa. Sem leitura, assume que sim.

        Chutar “não” numa leitura que falhou faria o app regravar a
        página por engano, e regravar é a operação cara: cria, ativa e
        apaga. Falha de leitura não é evidência de troca.
        """
        try:
            current = self._client.get(endpoints.PERK_CURRENT_PAGE)
        except ClientClosed:
            raise
        except LcuError:
            return True
        return same_page(current, watch)

    def _guard_page(self) -> None:
        """A cada tick: a página do app ainda é a ativa? Se não, volta.

        O app parava de olhar no instante em que gravava, e o cliente
        troca a página ativa bem depois disso. Medido no cliente real:
        página do app gravada às 08:05:34, recomendação do próprio
        cliente ativa às 08:07:18 — quase dois minutos depois, já com o
        campeão travado —, e a partida carregou as runas dele. Do lado
        do jogador isso é exatamente “o app não trocou a runa”, com o
        diário jurando que trocou.

        O que não se faz aqui é brigar com o jogador: `replaceable`
        deixa a escolha à mão dele encerrar a vigilância.
        """
        watch = self._page_watch
        if watch is None or not self._config.auto_runes:
            return
        if self._now() - self._page_checked_at < PAGE_CHECK_SECONDS:
            return
        self._page_checked_at = self._now()
        try:
            current = self._client.get(endpoints.PERK_CURRENT_PAGE)
            if same_page(current, watch):
                return
            if not replaceable(current):
                self._page_watch = None
                return
            if self._page_fixes >= MAX_PAGE_FIXES:
                self._page_watch = None
                self._complain(
                    "O cliente insiste em trocar a página de runas — "
                    "confira a runa antes de a partida começar."
                )
                return
            self._page_fixes += 1
            name = self._reinstall(watch)
        except ClientClosed:
            raise
        except LcuError as exc:
            self._log(f"Não deu para conferir a página de runas: {exc}")
            return
        if name is not None:
            self._log(f"O cliente trocou a página de runas — “{name}” de volta.")

    def _reinstall(self, watch: _Watch) -> str | None:
        """Põe a nossa de volta: ativando, ou criando de novo se sumiu."""
        try:
            if self._activate(watch):
                self._page_checked_at = self._now()
                return watch.name
        except ClientClosed:
            raise
        except LcuError:
            # A página não existe mais — o cliente a apagou para pôr a
            # dele. Não há o que ativar, há o que recriar.
            pass
        return self._write_page(
            watch.name, watch.style, watch.sub_style, watch.perks
        )

    def _create_page(self, body: dict) -> dict | None:
        """Cria a página. Permanente primeiro; temporária só se não couber.

        `isTemporary` parecia de graça: a página aparece na lista, dá
        para ativá-la e não entra na conta de `customPageCount`. O que
        ela não diz é de quem é a gaveta. É a mesma que o cliente usa
        para as páginas que ele próprio recomenda na seleção, e ele a
        esvazia quando quer. Medido: a nossa criada temporária às
        08:05:34, a recomendação do cliente ocupando o lugar às
        08:07:18 com o `recommendationId` dele, e a partida carregando
        as runas dele. Página temporária é página emprestada.

        Permanente ele não mexe. Por isso a ordem é esta, e a recusa
        tem uma resposta antes de desistir: a vaga que dá para abrir é
        a da nossa página de uma seleção anterior — apagar página do
        usuário continua fora de questão.

        A temporária fica para o único caso em que a permanente não tem
        saída: conta emprestada com todas as vagas ocupadas por páginas
        do dono. Lá, uma runa que talvez o cliente substitua ainda é
        melhor do que entrar em partida sem runa nenhuma — e agora há
        quem confira e a reponha enquanto a seleção durar.
        """
        try:
            return self._client.post(endpoints.PERK_PAGES, json=body)
        except ClientClosed:
            raise
        except LcuError:
            pass
        # A vaga que dá para abrir é a da nossa página de uma seleção
        # anterior, e só quando o cliente diz não haver nenhuma: apagar
        # a que está ativa por causa de uma recusa que tinha outro
        # motivo deixaria o jogador sem página se a segunda também
        # falhasse.
        if self._out_of_room():
            try:
                self._discard_old_pages()
                return self._client.post(endpoints.PERK_PAGES, json=body)
            except ClientClosed:
                raise
            except LcuError:
                pass
        try:
            return self._client.post(
                endpoints.PERK_PAGES, json={**body, "isTemporary": True}
            )
        except ClientClosed:
            raise
        except LcuError as exc:
            self._complain(
                "Sem espaço para uma página de runas — apague uma das "
                "suas ou desligue as runas automáticas."
                if self._out_of_room()
                else f"O cliente recusou a página de runas: {exc}"
            )
            return None

    # ---------- as opções de runa ----------

    def _serve_choice(self, champion_id: int) -> None:
        """Atende o clique numa opção de runa, no tick seguinte a ele.

        Um elo que não está entre as opções é ignorado em silêncio: só
        chegaria aqui um botão de uma seleção que já passou.

        Recusada a troca, a página de antes continua onde estava e ativa
        — `_install_page` só apaga a velha depois de ter a nova —, então
        o elo marcado na tela segue sendo verdade e não é mexido.
        """
        tier, self._requested_tier = self._requested_tier, None
        if tier is None:
            return
        build = self._options.get(tier)
        if build is None:
            return
        try:
            name = self._install_page(
                champion_id, build.style, build.sub_style, build.perks
            )
        except ClientClosed:
            raise
        except LcuError as exc:
            self._log(f"Não deu para trocar a página de runas: {exc}")
            return
        if name is None:
            return
        self._active_tier = tier
        self._log(f"Runas {option_label(tier)} aplicadas — página “{name}”.")
        self._publish_options()

    def _serve_matchup(self, champion_id: int) -> None:
        """Instala o que o guia do confronto trouxe, no tick do clique.

        Duas coisas saem daqui, e cada uma vale por si.

        O arsenal ganha uma aba “vs Fulano” ao lado da do campeão, do
        jeito que Blitz e Porofessor põem as suas na loja: quem quiser
        a leitura geral continua tendo, quem quiser a do confronto
        troca de aba dentro da partida, sem alt-tab.

        A runa do confronto vira mais um botão na lista de opções, e
        não uma troca automática. Ela é a leitura de um adversário que
        o jogador acabou de olhar por curiosidade, e trocar sozinho a
        página ativa a poucos segundos da partida seria decidir por ele
        o que ele não pediu.
        """
        ticket, self._requested_matchup = self._requested_matchup, None
        if ticket is None:
            return
        opponent, build = ticket
        try:
            if self._config.auto_items and build.pages:
                self._items.apply(
                    champion_id,
                    self._catalog.name(champion_id),
                    (*self._pages, *versus_pages(build.pages, opponent)),
                    self._map_id(),
                )
        except ClientClosed:
            raise
        except LcuError as exc:
            self._log(f"Não deu para montar o arsenal do confronto: {exc}")
        self._offer_matchup_runes(opponent, build)

    def _offer_matchup_runes(self, opponent: str, build: Build) -> None:
        """Põe a runa do confronto entre as opções, quando ela é outra.

        Igual a uma que já está na lista, não vira botão — a mesma
        regra de `rune_options` para dois elos que devolvem a mesma
        página. E o confronto anterior sai da lista quando entra o
        novo, a menos que seja o que está no cliente: aí o botão
        marcado precisa continuar existindo para dizer o que está
        ativo.
        """
        if not (self._config.auto_runes and self._config.auto_runes_options):
            return
        if not build.perks:
            return
        chave = f"{MATCHUP_PREFIX}{opponent}"
        for antiga in [
            key
            for key in self._options
            if key.startswith(MATCHUP_PREFIX)
            and key != chave
            and key != self._active_tier
        ]:
            del self._options[antiga]
        assinatura = (build.style, build.sub_style, build.perks)
        if any(
            (outra.style, outra.sub_style, outra.perks) == assinatura
            for key, outra in self._options.items()
            if key != chave
        ):
            return
        self._options[chave] = build
        self._publish_options()

    def _clear_options(self) -> None:
        # A geração muda antes de tudo: é o que faz uma busca de elos
        # ainda em voo largar o resultado em vez de o colar nesta tela.
        self._options_gen += 1
        self._options = {}
        self._active_tier = None
        self._requested_tier = None
        self._publish_options()

    def _publish_options(self) -> None:
        """Conta à tela o que há para escolher, e o que está no cliente.

        Fica calado enquanto não houver nada e nunca tiver havido: a
        maioria das seleções não tem opção alguma a mostrar.
        """
        if self._on_rune_options is None:
            return
        tiers = list(self._options)
        if not tiers and not self._published:
            return
        self._published = bool(tiers)
        # As builds vão junto para a tela poder desenhar a árvore de cada
        # elo. Vai uma cópia: o dicionário daqui é trocado inteiro pela
        # thread das opções, e a tela lê no seu próprio tempo.
        self._on_rune_options(tiers, self._active_tier, dict(self._options))

    def _discard_old_pages(self, keep: int | None = None) -> None:
        """Apaga a página que o app criou antes, e só ela.

        O nome que o app reconhece é o dele inteiro, com os dois pontos
        — o mesmo que ele escreve ao criar. Comparar só pelo prefixo
        levava junto uma página do usuário chamada, digamos, “LoL Queue
        Ranqueada”: nome parecido, dona diferente.
        """
        pages = self._client.get(endpoints.PERK_PAGES)
        if not isinstance(pages, list):
            return
        for page in pages:
            name = page.get("name")
            if not isinstance(name, str) or not name.startswith(f"{PAGE_PREFIX}: "):
                continue
            if not page.get("isDeletable", True):
                continue
            page_id = page.get("id")
            if page_id is None or page_id == keep:
                continue
            self._client.delete(endpoints.PERK_PAGE.format(page_id=page_id))

    def _has_room(self) -> bool:
        """O palpite do cliente sobre haver vaga. Palpite, não veredito."""
        inventory = self._client.get(endpoints.PERK_INVENTORY)
        if not isinstance(inventory, dict):
            return True
        return bool(inventory.get("canAddCustomPage", True))

    def _out_of_room(self) -> bool:
        """Se a falta de vaga explica a recusa que o cliente acabou de dar.

        Serve só para escolher a frase certa depois do erro, então uma
        segunda falha aqui não pode virar exceção: sem resposta, a
        recusa é descrita como veio, sem inventar o motivo.
        """
        try:
            return not self._has_room()
        except LcuError:
            return False

    def _complain(self, message: str) -> None:
        """Diz o que deu errado com a página — uma vez por seleção.

        `apply` roda a cada tick enquanto o campeão está travado, e a
        mesma frase repetida dezenas de vezes não informa mais que a
        primeira: só empurra para fora do diário as linhas que ainda
        não foram lidas. Muda o motivo, muda a frase, e ela sai de novo.
        """
        if message == self._complaint:
            return
        self._complaint = message
        self._log(message)
