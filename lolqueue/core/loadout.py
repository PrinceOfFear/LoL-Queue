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
    thread: threading.Thread | None = None
    result: Build | None = None


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
        on_analysis: Callable[[int, str, Build | None], None] | None = None,
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

    def reset(self) -> None:
        self._done_for = None
        self._complaint = ""
        self._pages = ()
        self._requested_matchup = None
        # A thread em voo, se houver, é daemon e some sozinha; o que
        # importa é não colar a resposta de uma seleção na seguinte.
        self._pending = None
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
        if champion_id <= 0:
            return
        if champion_id == self._done_for:
            # Já equipado. O que ainda pode chegar aqui são os
            # cliques do usuário na tela — a opção de runa e o
            # adversário da rota —, que rodam neste tick e não em cima
            # da thread da GUI.
            self._serve_matchup(champion_id)
            self._serve_choice(champion_id)
            return

        external = self._external(champion_id, session)
        if external is PENDING:
            # A fonte externa ainda está respondendo. Sair sem marcar
            # é o que faz o próximo tick voltar aqui para recolher.
            return

        # Marcado antes de agir: uma falha no meio do caminho não pode
        # virar uma tentativa por tick pelo resto da seleção.
        self._done_for = champion_id

        # Antes de equipar, e fora do bloco protegido, porque a leitura
        # não fala com o cliente: mesmo que aplicar runa falhe adiante,
        # o que já sabemos sobre o campeão vale para ser mostrado.
        if self._on_analysis is not None:
            # Import tardio como os outros usos aqui: `champ_select`
            # importa este módulo, e no topo isto fecharia o ciclo.
            from .champ_select import local_position

            self._on_analysis(champion_id, local_position(session), external)

        try:
            # O arsenal vem primeiro porque nao depende da Riot: se a
            # recomendacao dela faltar, ele ainda tem por que existir.
            if self._config.auto_items and external is not None:
                # Guardado para o confronto: escolhido o adversário, a
                # loja recebe as duas leituras juntas, e sem isto a do
                # campeão sumiria na segunda gravação.
                self._pages = tuple(external.pages)
                self._items.apply(
                    champion_id,
                    self._catalog.name(champion_id),
                    self._pages,
                    self._map_id(),
                )
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
            return None

        search = self._pending
        if search is None or search.champion_id != champion_id:
            search = self._start(champion_id, session)

        if search.thread is not None and search.thread.is_alive():
            if self._now() - search.started < WAIT_SECONDS:
                return PENDING
            self._pending = None
            self._log("O OP.GG demorou; usando a recomendação da Riot.")
            return None

        self._pending = None
        return search.result

    def _start(self, champion_id: int, session: dict) -> _Search:
        from .champ_select import local_position

        # O alias, não o nome: o cliente traduz o nome, e quem está
        # do outro lado só conhece o identificador da Riot.
        champion = self._catalog.alias(champion_id)
        position = local_position(session)
        aram = self._map_id() == ARAM_MAP
        search = _Search(champion_id=champion_id, started=self._now())
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
        self._client.patch(
            endpoints.CHAMP_SELECT_MY_SELECTION,
            json={"spell1Id": first, "spell2Id": second},
        )
        self._log(f"Feitiços do {origem} aplicados.")

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
        name = f"{PAGE_PREFIX}: {self._catalog.name(champion_id)}"
        if not self._has_room():
            self._discard_old_pages()

        try:
            page = self._client.post(
                endpoints.PERK_PAGES,
                json={
                    "name": name,
                    "primaryStyleId": style,
                    "subStyleId": sub_style,
                    "selectedPerkIds": list(perks),
                },
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
        page_id = page.get("id") if isinstance(page, dict) else None
        if page_id is None:
            self._complain("O cliente não devolveu a página de runas criada.")
            return None
        # Criar não ativa: sem este passo o jogador entraria na partida
        # com a página que estava selecionada antes.
        self._client.put(endpoints.PERK_CURRENT_PAGE, json=page_id)
        self._discard_old_pages(keep=page_id)
        return name

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
