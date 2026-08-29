"""As configurações de dentro do jogo, copiadas da conta principal.

O perfil por conta em `accounts.py` cuida do app: rota pedida, lista de
campeões, tecla do Flash. Nada disso é o que o jogador vê quando a
partida começa — as teclas das habilidades, dos feitiços de invocador e
dos itens, a movimentação, a interface, a câmera e o minimapa moram no
cliente do LoL, presos à conta que está logada. Entrar na conta de outra
pessoa é encontrar tudo trocado de lugar, e é assim que se perde uma
partida sem nunca ter errado uma decisão.

O cliente guarda esses ajustes em duas rotas (`GAME_SETTINGS` e
`INPUT_SETTINGS`) que aceitam PATCH parcial — confirmado contra o
cliente real. Então dá para tirar uma fotografia da conta principal e
despejá-la nas outras.

Duas coisas ficam de fora de propósito:

*   O bloco `Performance` e o modo de vídeo (`WindowMode`,
    `WaitForVerticalSync`). São do computador, não do jogador: copiar a
    qualidade gráfica de uma máquina boa para uma fraca estraga o jogo,
    e reescrever o modo de vídeo seria o app brigando com a própria
    captura do minimapa, que é quem lê essa opção.
*   O momento. A troca de conta não é instantânea no cliente: ele ainda
    está baixando os ajustes da conta nova quando anuncia quem entrou.
    Escrever nesse intervalo seria escrever por cima de algo que vai ser
    sobrescrito logo em seguida, então a cópia é adiada e refeita uma
    segunda vez alguns segundos depois.

A fotografia só é tirada quando o usuário pede. Tirá-la sozinho, na
troca de conta, correria o risco de fotografar a conta errada — e uma
fotografia errada se espalharia para todas as outras contas.
"""

from __future__ import annotations

import time
from typing import Callable

from ..lcu.client import LcuError
from ..lcu.endpoints import GAME_SETTINGS, INPUT_SETTINGS
from .accounts import Accounts, account_key
from .identity import Identity

#: Quanto esperar depois do anúncio da conta para escrever, e de novo.
#: A primeira pega o caso comum; a segunda cobre o cliente que demorou
#: mais para terminar de carregar o que era da conta que entrou.
APPLY_DELAYS = (8.0, 25.0)

#: Blocos que são da máquina, não de quem joga.
MACHINE_BLOCKS = ("Performance",)
#: Ajustes soltos que são da máquina, dentro de blocos que não são.
MACHINE_KEYS = {"General": ("WindowMode", "WaitForVerticalSync")}


def strip_machine(settings: dict) -> dict:
    """Tira da fotografia o que é do computador e não do jogador."""
    if not isinstance(settings, dict):
        return {}
    clean: dict = {}
    for block, value in settings.items():
        if block in MACHINE_BLOCKS:
            continue
        if isinstance(value, dict) and block in MACHINE_KEYS:
            value = {
                name: item
                for name, item in value.items()
                if name not in MACHINE_KEYS[block]
            }
        clean[block] = value
    return clean


def capture(client) -> dict:
    """A fotografia das configurações de jogo da conta logada agora."""
    return {
        "game": strip_machine(_read(client, GAME_SETTINGS)),
        "input": _read(client, INPUT_SETTINGS),
    }


def apply(client, snapshot: dict) -> list[str]:
    """Despeja a fotografia no cliente. Devolve o que foi escrito.

    A limpeza é refeita aqui: uma fotografia antiga, gravada por uma
    versão que ainda copiava o modo de vídeo, não pode trocar a tela de
    quem atualizar o app.
    """
    if not isinstance(snapshot, dict):
        return []
    written: list[str] = []
    game = strip_machine(snapshot.get("game") or {})
    if game:
        client.patch(GAME_SETTINGS, json=game)
        written.append("interface")
    keys = snapshot.get("input") or {}
    if isinstance(keys, dict) and keys:
        client.patch(INPUT_SETTINGS, json=keys)
        written.append("teclas")
    return written


def _read(client, path: str) -> dict:
    answer = client.get(path)
    return answer if isinstance(answer, dict) else {}


class GameSettingsSync:
    """Leva as configurações do jogo da conta principal para as outras.

    Vive na thread da vigia de conexão, que é quem tem o cliente da LCU.
    A janela só deixa bilhetes (`request_capture`, `request_apply`);
    quem os lê é o `tick`, do outro lado.
    """

    def __init__(
        self,
        client,
        accounts: Accounts,
        save: Callable[[], None] | None = None,
        log: Callable[[str], None] | None = None,
        on_change: Callable[[], None] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._accounts = accounts
        self._save = save or (lambda: None)
        self._log = log or (lambda message: None)
        self._on_change = on_change or (lambda: None)
        self._now = now
        self._due: list[float] = []
        self._capture = ""
        self._apply = ""

    # -- pedidos de fora ------------------------------------------------

    def account_arrived(self, identity: Identity) -> None:
        """Outra conta entrou: agenda a cópia, se houver o que copiar."""
        key = account_key(identity)
        if key == self._accounts.main:
            # A principal é o modelo; ela não recebe cópia de ninguém.
            self._due = []
            return
        if not self._accounts.main_game_settings():
            return
        agora = self._now()
        self._due = [agora + espera for espera in APPLY_DELAYS]
        self._log(
            "Configurações do jogo da conta principal serão aplicadas "
            "nesta conta em instantes."
        )

    def request_capture(self, key: str) -> None:
        """A janela pediu para guardar as configurações desta conta."""
        self._capture = key

    def request_apply(self, _key: str = "") -> None:
        """A janela pediu para aplicar agora, sem esperar."""
        self._apply = "agora"

    # -- trabalho -------------------------------------------------------

    def tick(self) -> None:
        """Uma volta do relógio da vigia: faz o que estiver na hora."""
        key, self._capture = self._capture, ""
        if key:
            self._do_capture(key)
        asked, self._apply = self._apply, ""
        if asked:
            self._due = []
            self._do_apply(asked=True)
            return
        if self._due and self._now() >= self._due[0]:
            self._due.pop(0)
            self._do_apply()

    def _do_capture(self, key: str) -> None:
        account = self._accounts.accounts.get(key)
        if account is None:
            return
        try:
            snapshot = capture(self._client)
        except LcuError as exc:
            self._log(f"Não consegui ler as configurações do jogo: {exc}")
            return
        if not snapshot.get("game") and not snapshot.get("input"):
            self._log(
                "O cliente do LoL não devolveu as configurações do jogo. "
                "Tente de novo com ele na tela inicial."
            )
            return
        self._accounts.set_game_settings(key, snapshot)
        self._store()
        self._log(
            f"Configurações do jogo de {account.label} guardadas: teclas de "
            "habilidades, feitiços, itens, movimentação e interface. Toda "
            "conta que entrar neste PC vai receber essas configurações."
        )

    def _do_apply(self, asked: bool = False) -> None:
        snapshot = self._accounts.main_game_settings()
        if not snapshot:
            if asked:
                self._log(
                    "Nenhuma configuração de jogo guardada ainda. Entre na "
                    "conta principal e use o botão de guardar."
                )
            return
        try:
            written = apply(self._client, snapshot)
        except LcuError as exc:
            self._log(f"Não consegui aplicar as configurações do jogo: {exc}")
            self._due = []
            return
        if not written:
            return
        self._log(
            "Configurações do jogo da conta principal aplicadas nesta conta "
            f"({' e '.join(written)}). Valem a partir da próxima partida."
        )

    def _store(self) -> None:
        try:
            self._save()
        except OSError as exc:
            self._log(f"Não consegui gravar as contas: {exc}")
        # A tela mostra quem tem fotografia guardada, e quem gravou foi
        # esta thread. O aviso atravessa para a janela redesenhar.
        self._on_change()
