"""Quem é o jogador dentro da partida em andamento.

Sem isso o aviso sai errado: dizer "na sua selva de cima" para quem está
na rota de baixo do lado vermelho não ajuda ninguém. Precisamos de três
fatos antes de abrir a boca — de que lado o jogador está, em que rota ele
está, e quem é o jungler inimigo.

A fonte é a Live Client Data API, um servidor HTTP que o próprio jogo
levanta em 127.0.0.1:2999 enquanto a partida roda. É público e não pede
credencial nenhuma; some junto com a partida.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import requests
import urllib3

BASE_URL = "https://127.0.0.1:2999/liveclientdata"

# Como a Riot chama os times. ORDER nasce embaixo à esquerda no mapa.
ORDER = "ORDER"
CHAOS = "CHAOS"

BLUE = 1
RED = -1

# As rotas com o nome que a API usa, traduzidas para o nome que o
# jogador fala. UTILITY é o suporte, que anda com a rota de baixo.
TOP = "TOP"
JUNGLE = "JUNGLE"
MID = "MIDDLE"
BOT = "BOTTOM"
SUPPORT = "UTILITY"

LANE_NAMES = {
    TOP: "rota de cima",
    JUNGLE: "selva",
    MID: "rota do meio",
    BOT: "rota de baixo",
    SUPPORT: "rota de baixo",
}

# Onde cada rota briga, em coordenadas de mundo. Serve de palpite para a
# posição do jogador quando não dá para achar o ícone dele no minimapa.
# A rota de cima briga na dobra de cima à esquerda, a de baixo na dobra
# de baixo à direita, e o meio no meio.
LANE_ANCHORS = {
    TOP: (0.13, 0.13),
    MID: (0.50, 0.50),
    BOT: (0.87, 0.87),
    SUPPORT: (0.87, 0.87),
}
# A selva não tem ponto fixo: o jungler está sempre andando. O palpite
# vira o centro da própria metade, que é onde ele passa a maior parte
# do tempo.
JUNGLE_ANCHOR = {BLUE: (0.32, 0.68), RED: (0.68, 0.32)}


class LiveGameUnavailable(RuntimeError):
    """Não há partida rodando, ou o jogo ainda não abriu a porta 2999."""


@dataclass(frozen=True)
class Player:
    """Um dos dez jogadores da partida."""

    name: str
    champion: str
    team: str
    position: str
    smite: bool = False

    @property
    def side(self) -> int:
        """1 para o lado azul, -1 para o vermelho."""
        return BLUE if self.team == ORDER else RED

    @property
    def is_jungler(self) -> bool:
        """Se este jogador joga a selva. A única definição disto no app.

        A API só preenche `position` em fila ranqueada e draft. Fora
        dela o feitiço entrega: quem leva Punir vai para a selva.

        A ordem importa, e havia duas regras diferentes espalhadas pelo
        código — uma aqui, contando Punir sempre, e outra dentro de
        `my_anchor`, contando Punir só na falta de rota declarada. Um
        meio de Punir declarado pela API caía nas duas ao mesmo tempo: a
        âncora dele ficava no meio do mapa, correta, enquanto o aviso o
        tratava como jungler e gritava "cuidado" para metade do mapa
        inteira. Rota declarada manda; o feitiço só fala quando ninguém
        declarou nada. É a mesma ordem que `enemy_jungler` usa do outro
        lado do mapa.
        """
        if self.position:
            return self.position == JUNGLE
        return self.smite


@dataclass(frozen=True)
class LiveGame:
    """A partida vista pelos olhos de um jogador específico."""

    me: Player
    allies: tuple[Player, ...]
    enemies: tuple[Player, ...]
    flip_minimap: bool = False

    @property
    def side(self) -> int:
        return self.me.side

    @property
    def lane(self) -> str:
        return self.me.position

    @property
    def lane_name(self) -> str:
        """A rota do jogador com o nome que ele mesmo usaria."""
        return LANE_NAMES.get(self.me.position, "")

    @property
    def jungler_has_a_twin(self) -> bool:
        """Se o campeão do jungler inimigo também está deste lado do mapa.

        O minimapa é lido pelo retrato do campeão, e o retrato é o mesmo
        nos dois times: o anel colorido em volta fica de fora da
        comparação de propósito, porque incluí-lo derrubava o acerto. O
        preço é este caso — os dois times com o mesmo campeão — em que o
        aliado passeando pela própria selva dispara o aviso de gank do
        inimigo. Em ranqueada e no draft não acontece, porque lá o
        campeão é único na partida; na fila cega e no olho por olho,
        acontece.

        Não dá para consertar sem trocar a leitura do minimapa inteira,
        então o que resta é dizer que o aviso ficou menos confiável em
        vez de deixar o jogador descobrir sozinho no primeiro susto.
        """
        jungler = self.enemy_jungler
        if jungler is None:
            return False
        nome = jungler.champion.casefold()
        return any(p.champion.casefold() == nome for p in (self.me, *self.allies))

    @property
    def enemy_jungler(self) -> Player | None:
        """O inimigo que interessa. None quando não dá para ter certeza.

        A posição declarada pela API vale mais que o feitiço. Empatar as
        duas coisas emudecia a partida inteira sempre que alguém do outro
        lado levava Punir fora da selva — um top de Punir e Fantasma, um
        suporte que pegou o feitiço errado — porque aí eram dois
        candidatos e o aviso preferia calar. Quando a API diz quem é o
        jungler, ela decide sozinha.

        Só onde ninguém tem posição declarada — fila cega, olho por olho
        — o Punir volta a ser o único sinal. Aí, sim, dois Punir são
        dúvida legítima: chutar mandaria o jogador para o lado errado do
        mapa, que é pior que não avisar nada.
        """
        declarados = [p for p in self.enemies if p.position == JUNGLE]
        if declarados:
            return declarados[0] if len(declarados) == 1 else None
        punidores = [p for p in self.enemies if p.smite]
        return punidores[0] if len(punidores) == 1 else None

    @property
    def anchor_is_a_guess(self) -> bool:
        """Se `my_anchor` é chute cego, e não palpite com base em algo.

        A API só preenche `position` em ranqueada e em seleção com
        draft. Fila cega, normal e personalizada chegam com todo mundo
        sem rota, e aí a âncora cai no centro do mapa — ou seja, o app
        trata o jogador como se ele fosse o meio. Esse é justamente o
        erro que deu origem a este módulo, e ele tinha voltado pela
        porta dos fundos: um top de fila cega ouvia "longe de você" com
        o jungler inimigo dentro da torre dele.
        """
        return not self.me.position and not self.me.smite

    @property
    def my_anchor(self) -> tuple[float, float]:
        """Onde o jogador provavelmente está, em coordenadas de mundo.

        É palpite, não medição: vale enquanto o ícone dele não for
        localizado no minimapa. Quando nem o palpite existe — veja
        `anchor_is_a_guess` — quem usa isto não deve afirmar distância.
        """
        if self.me.is_jungler:
            return JUNGLE_ANCHOR[self.side]
        return LANE_ANCHORS.get(self.me.position, (0.5, 0.5))

    def to_world(self, mx: float, my: float) -> tuple[float, float]:
        """Converte ponto do minimapa em ponto do mundo.

        Normalmente os dois são a mesma coisa. Mas o jogo tem uma opção
        que gira o minimapa 180 graus para a base do jogador ficar sempre
        embaixo à esquerda; com ela ligada, quem está no lado vermelho vê
        tudo de cabeça para baixo e o aviso sairia espelhado.
        """
        if self.flip_minimap and self.side == RED:
            return 1.0 - mx, 1.0 - my
        return mx, my


def _smite(entry: dict[str, Any]) -> bool:
    """Procura Punir nos dois espaços de feitiço."""
    spells = entry.get("summonerSpells") or {}
    for slot in ("summonerSpellOne", "summonerSpellTwo"):
        nome = (spells.get(slot) or {}).get("displayName") or ""
        if "smite" in nome.lower() or "punir" in nome.lower():
            return True
    return False


def _name(entry: dict[str, Any]) -> str:
    """O nome do jogador mudou de campo quando vieram as Riot ID."""
    return entry.get("riotId") or entry.get("summonerName") or ""


def _player(entry: dict[str, Any]) -> Player:
    return Player(
        name=_name(entry),
        champion=entry.get("championName") or "",
        team=entry.get("team") or ORDER,
        position=(entry.get("position") or "").upper(),
        smite=_smite(entry),
    )


def parse(
    active_name: str,
    player_list: list[dict[str, Any]],
    flip_minimap: bool = False,
) -> LiveGame:
    """Monta a visão da partida a partir das respostas cruas da API.

    Fica separado da chamada HTTP para poder ser testado sem partida.
    """
    jogadores = [_player(e) for e in player_list]
    eu = next((p for p in jogadores if p.name == active_name), None)
    if eu is None:
        # A API às vezes devolve o nome ativo sem a etiqueta (#BR1) que
        # aparece na lista, então vale comparar só a parte da frente.
        curto = active_name.split("#")[0]
        eu = next((p for p in jogadores if p.name.split("#")[0] == curto), None)
    if eu is None:
        raise LiveGameUnavailable(
            f"jogador {active_name!r} não está na lista da partida"
        )

    return LiveGame(
        me=eu,
        allies=tuple(p for p in jogadores if p.team == eu.team and p is not eu),
        enemies=tuple(p for p in jogadores if p.team != eu.team),
        flip_minimap=flip_minimap,
    )


def fetch(timeout: float = 1.0, flip_minimap: bool = False) -> LiveGame:
    """Pergunta ao jogo quem está jogando. Só funciona durante a partida.

    O certificado é autoassinado da Riot; ignorar a verificação só é
    aceitável porque o destino é sempre a própria máquina.

    O aviso de conexão insegura é calado só aqui dentro, e não com um
    `disable_warnings` no topo do módulo como era antes. A diferença
    importa: aquilo desligava o aviso no processo inteiro, para sempre,
    no instante em que alguém importasse este arquivo — inclusive para
    qualquer outra parte do app que fosse falar com a internet de
    verdade. Silenciar um aviso de TLS por engano, em código que fala
    com a máquina do jogador, é um preço alto por uma linha de log.
    """
    session = requests.Session()
    session.verify = False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "ignore", urllib3.exceptions.InsecureRequestWarning
            )
            ativo = session.get(f"{BASE_URL}/activeplayername", timeout=timeout)
            lista = session.get(f"{BASE_URL}/playerlist", timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise LiveGameUnavailable("partida não está rodando") from exc
    finally:
        session.close()

    if ativo.status_code >= 400 or lista.status_code >= 400:
        raise LiveGameUnavailable("partida ainda não liberou os dados")

    try:
        return parse(ativo.json(), lista.json(), flip_minimap=flip_minimap)
    except ValueError as exc:
        raise LiveGameUnavailable("partida devolveu resposta inválida") from exc
