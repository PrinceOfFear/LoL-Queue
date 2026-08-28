"""As árvores de runa, no formato em que o jogo as desenha.

O OP.GG entrega uma página como nove ids soltos: quatro da árvore
primária, dois da secundária e três fragmentos. Isso basta para *montar*
a página no cliente, mas não para *mostrá-la* — nove números não dizem
nada a quem olha.

Este módulo traz do próprio cliente o que falta: o nome e o ícone de
cada runa, e a forma das árvores (que runa mora em que fileira). Com
isso, `tree()` transforma os nove ids na mesma grade que aparece na tela
de runas do jogo — fileira por fileira, com as opções não escolhidas no
lugar, apagadas.

Como o resto dos catálogos daqui, a carga é preguiçosa e tolerante: se a
API falhar, o catálogo fica vazio e quem chama continua de pé — sem
árvore para desenhar, não com uma árvore errada.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..lcu import endpoints
from ..lcu.client import LcuError

#: Os tipos de slot que a LCU usa, na ordem em que o jogo os desenha.
#: A chave é a fileira de cima; as `kMixedRegularSplashable` são as três
#: fileiras comuns; as `kStatMod` são os fragmentos, iguais nas cinco
#: árvores.
KEYSTONE_SLOT = "kKeyStone"
REGULAR_SLOT = "kMixedRegularSplashable"
SHARD_SLOT = "kStatMod"


@dataclass(frozen=True)
class Perk:
    """Uma runa: o que dá para mostrar dela na tela."""

    id: int
    name: str
    icon: str
    description: str = ""


@dataclass(frozen=True)
class Style:
    """Uma árvore inteira, com a forma das suas fileiras."""

    id: int
    name: str
    icon: str
    #: Fileiras de runa, da chave para baixo. Cada uma é a lista de
    #: opções daquela linha, na ordem do jogo.
    rows: tuple[tuple[int, ...], ...] = ()
    #: As três fileiras de fragmento. Iguais em todas as árvores, mas
    #: guardadas por árvore porque é assim que a LCU as entrega.
    shards: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True)
class Row:
    """Uma fileira desenhada: as opções e a que a build escolheu.

    `chosen` pode ser `None` numa fileira da árvore secundária — lá se
    escolhem duas runas entre três fileiras, então uma fica sem marca,
    exatamente como no jogo.
    """

    perks: tuple[Perk, ...]
    chosen: int | None = None


@dataclass(frozen=True)
class Tree:
    """Uma página de runas pronta para desenhar."""

    primary: Style
    secondary: Style
    primary_rows: tuple[Row, ...]
    secondary_rows: tuple[Row, ...]
    shard_rows: tuple[Row, ...]


class PerkCatalog:
    """Nomes, ícones e a forma das árvores, vindos do cliente."""

    def __init__(self, client) -> None:
        self._client = client
        self._perks: dict[int, Perk] = {}
        self._styles: dict[int, Style] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Carrega uma vez só. Falha não estoura: o catálogo fica vazio.

        As duas rotas precisam responder. Com os estilos mas sem as
        runas dava para desenhar a grade, mas todas as casas sairiam
        vazias — pior do que não desenhar.
        """
        if self._loaded:
            return
        try:
            perks = self._client.get(endpoints.PERKS)
            styles = self._client.get(endpoints.PERK_STYLES)
        except LcuError:
            return
        if not isinstance(perks, list) or not isinstance(styles, list):
            return

        by_id: dict[int, Perk] = {}
        for entry in perks:
            if not isinstance(entry, dict):
                continue
            perk_id = entry.get("id")
            name = entry.get("name")
            if not isinstance(perk_id, int) or not isinstance(name, str):
                continue
            by_id[perk_id] = Perk(
                id=perk_id,
                name=name,
                icon=str(entry.get("iconPath") or ""),
                description=str(entry.get("shortDesc") or ""),
            )

        by_style: dict[int, Style] = {}
        for entry in styles:
            if not isinstance(entry, dict):
                continue
            style_id = entry.get("id")
            name = entry.get("name")
            if not isinstance(style_id, int) or not isinstance(name, str):
                continue
            rows: list[tuple[int, ...]] = []
            shards: list[tuple[int, ...]] = []
            for slot in entry.get("slots") or []:
                if not isinstance(slot, dict):
                    continue
                ids = tuple(p for p in slot.get("perks") or [] if isinstance(p, int))
                if not ids:
                    continue
                kind = slot.get("type")
                if kind in (KEYSTONE_SLOT, REGULAR_SLOT):
                    rows.append(ids)
                elif kind == SHARD_SLOT:
                    shards.append(ids)
            by_style[style_id] = Style(
                id=style_id,
                name=name,
                icon=str(entry.get("iconPath") or ""),
                rows=tuple(rows),
                shards=tuple(shards),
            )

        if not by_id or not by_style:
            return
        self._perks = by_id
        self._styles = by_style
        self._loaded = True

    def perk(self, perk_id: int) -> Perk:
        """A runa, ou um substituto com o id no lugar do nome."""
        return self._perks.get(perk_id) or Perk(
            id=perk_id, name=f"#{perk_id}", icon=""
        )

    def style(self, style_id: int) -> Style | None:
        return self._styles.get(style_id)

    def icons(self) -> list[str]:
        """Todo caminho de imagem que o catálogo conhece, sem repetir."""
        paths = {perk.icon for perk in self._perks.values() if perk.icon}
        paths.update(style.icon for style in self._styles.values() if style.icon)
        return sorted(paths)

    def tree(self, style_id: int, sub_style_id: int, perks) -> Tree | None:
        """Monta a grade da página a partir dos ids escolhidos.

        Não confia na ordem em que os ids chegam: para cada fileira,
        procura qual dos escolhidos mora nela. Assim uma fonte que
        entregue as runas fora de ordem ainda cai no lugar certo — e uma
        runa que não pertença a árvore nenhuma simplesmente não marca
        nada, em vez de marcar a casa errada.
        """
        primary = self.style(style_id)
        secondary = self.style(sub_style_id)
        if primary is None or secondary is None:
            return None
        ids = [p for p in perks if isinstance(p, int)]
        if not ids:
            return None
        chosen = set(ids)
        # Os fragmentos são o único caso em que a ordem importa: o mesmo
        # id aparece em mais de uma fileira (5008 está na primeira e na
        # segunda), então procurar "qual escolhido mora nesta fileira"
        # marcaria a de cima duas vezes e deixaria a de baixo vazia. Aí
        # vale a posição — que é como as fontes os entregam, uma por
        # fileira. As runas comuns não têm esse problema: cada uma mora
        # numa fileira só, e casar por pertencimento aguenta receber os
        # ids fora de ordem.
        shard_ids = ids[-len(primary.shards):] if primary.shards else []
        return Tree(
            primary=primary,
            secondary=secondary,
            primary_rows=self._rows(primary.rows, chosen),
            secondary_rows=self._rows(secondary.rows[1:], chosen),
            shard_rows=self._shard_rows(primary.shards, shard_ids),
        )

    def _shard_rows(self, rows, ids) -> tuple[Row, ...]:
        """As fileiras de fragmento, casadas por posição.

        Um id que não pertença à fileira em que caiu não marca nada: é
        sinal de que vieram menos fragmentos do que fileiras, e marcar
        assim mesmo inventaria uma escolha que a fonte não fez.
        """
        drawn: list[Row] = []
        for index, row in enumerate(rows):
            picked = ids[index] if index < len(ids) else None
            drawn.append(
                Row(
                    perks=tuple(self.perk(p) for p in row),
                    chosen=picked if picked in row else None,
                )
            )
        return tuple(drawn)

    def _rows(self, rows, chosen: set[int]) -> tuple[Row, ...]:
        """Cada fileira com as suas opções e a escolhida, se houver.

        A árvore secundária entra aqui sem a fileira da chave: no jogo
        não dá para levar a runa-chave de outra árvore, então mostrá-la
        seria oferecer o que não existe.
        """
        drawn: list[Row] = []
        for ids in rows:
            picked = next((p for p in ids if p in chosen), None)
            drawn.append(
                Row(perks=tuple(self.perk(p) for p in ids), chosen=picked)
            )
        return tuple(drawn)
