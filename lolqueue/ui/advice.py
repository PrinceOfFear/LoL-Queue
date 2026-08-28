"""O que cada lista de campeões merece avisar ao usuário.

Fica separado da tela por ser onde mora a armadilha do app: uma lista
pode estar impecável e mesmo assim não valer nada — porque a rota tem
lista própria, porque a automação está desligada, ou porque não há
ninguém nela para escolher. Nada disso dá erro; tudo falha calado na
partida, que é tarde demais para descobrir.

Sem Qt de propósito, para que o texto de cada situação seja testado
direto.
"""

from __future__ import annotations

from ..config import POSITIONS, position_name

#: Chave da lista que vale quando a rota não tem lista própria. Vazia de
#: propósito: é o mesmo valor que o cliente manda em `assignedPosition`
#: nos modos que não distribuem rota.
GENERAL = ""

#: Rótulos curtos: a coluna não comporta "Atirador" e "Suporte" inteiros
#: em seis abas lado a lado.
TAB_LABELS: dict[str, str] = {
    GENERAL: "GERAL",
    "top": "TOPO",
    "jungle": "SELVA",
    "middle": "MEIO",
    "bottom": "ADC",
    "utility": "SUP",
}

TAB_ORDER: tuple[str, ...] = (GENERAL, *POSITIONS)


def join_names(names: list[str]) -> str:
    """Junta rótulos como se escreve à mão: A, B e C."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} e {names[-1]}"


def pick_notice(
    tab: str, lists: dict[str, list[int]], auto_pick: bool
) -> tuple[str, bool]:
    """Aviso da aba aberta na prioridade de escolha.

    Devolve o texto e se ele é alerta — o que muda a cor. Alertar por
    tudo não alertaria por nada, então só recebe destaque a situação em
    que a lista à vista não vai fazer o que aparenta.
    """
    if not auto_pick:
        return "A escolha automática está desligada — nenhuma lista daqui é usada.", True

    if tab != GENERAL:
        return _lane_notice(tab, lists)
    return _general_notice(lists)


def _lane_notice(tab: str, lists: dict[str, list[int]]) -> tuple[str, bool]:
    if lists.get(tab):
        return f"Vale quando você cair de {position_name(tab)}.", False
    if lists.get(GENERAL):
        return "Sem lista própria — esta rota usa a lista geral.", False
    # Sem lista aqui e sem geral, cair nesta rota é ficar sem escolha.
    return "Sem lista própria e a geral está vazia — ninguém será escolhido.", True


def _general_notice(lists: dict[str, list[int]]) -> tuple[str, bool]:
    covered = [position for position in POSITIONS if lists.get(position)]
    uncovered = [position for position in POSITIONS if not lists.get(position)]

    if lists.get(GENERAL):
        if not covered:
            return "Vale para todas as rotas.", False
        labels = [TAB_LABELS[position] for position in covered]
        return f"{join_names(labels)} têm lista própria e não usam esta.", True

    if not uncovered:
        return "Toda rota tem lista própria — esta não é usada.", False
    # A falha que morde de verdade: a rota sorteada não tem ninguém.
    labels = [TAB_LABELS[position] for position in uncovered]
    return f"Vazia — em {join_names(labels)} nada será escolhido.", True


def ban_notice(ids: list[int], auto_ban: bool) -> tuple[str, bool]:
    """Aviso da lista de banimento, que não se divide por rota."""
    if not auto_ban:
        return "O banimento automático está desligado — esta lista não é usada.", True
    if not ids:
        return "Vazia — a vez de banir passa sozinha, sem escolher ninguém.", False
    return "Bane o primeiro da lista que ainda estiver livre.", False
