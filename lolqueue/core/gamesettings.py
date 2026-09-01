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

#: Quando a conferência reprova, quanto esperar antes de reescrever, e
#: quantas rodadas no total. O cliente costuma terminar de carregar a
#: conta em menos de um minuto; passar disso é sinal de que o problema
#: não é tempo, e insistir só encheria o diário.
RETRY_DELAY = 12.0
MAX_ROUNDS = 5

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


def wanted(snapshot: dict, hold: dict | None = None) -> tuple[dict, dict]:
    """O que se quer escrever em cada rota, já limpo e já ressalvado.

    A limpeza é refeita aqui: uma fotografia antiga, gravada por uma
    versão que ainda copiava o modo de vídeo, não pode trocar a tela de
    quem atualizar o app.

    `hold` é o que outra parte do app está segurando nesta mesma rota
    agora — na prática, o silêncio de antes da partida. Sem isso a
    cópia passava por cima do que o silêncio tinha acabado de escrever,
    porque as duas coisas mandam PATCH para `GAME_SETTINGS` e a
    fotografia da conta principal tem o chat ligado.
    """
    if not isinstance(snapshot, dict):
        return {}, {}
    game = strip_machine(snapshot.get("game") or {})
    if game and hold:
        game = _merge(game, hold)
    keys = snapshot.get("input") or {}
    return game, keys if isinstance(keys, dict) else {}


def apply(client, snapshot: dict, hold: dict | None = None) -> list[str]:
    """Despeja a fotografia no cliente. Devolve o que foi escrito."""
    game, keys = wanted(snapshot, hold)
    written: list[str] = []
    if game:
        client.patch(GAME_SETTINGS, json=game)
        written.append("interface")
    if keys:
        client.patch(INPUT_SETTINGS, json=keys)
        written.append("teclas")
    return written


def mismatches(client, snapshot: dict, hold: dict | None = None) -> list[str]:
    """O que o cliente continua devolvendo diferente do que se escreveu.

    O PATCH responde 2xx e mesmo assim não gruda: durante a troca de
    conta o cliente ainda está baixando os ajustes de quem entrou e
    escreve por cima logo depois. Era esse o "volta nas config da
    conta" — e, sem conferir, o app anunciava sucesso e o jogador
    clicava no botão à mão seis, sete vezes seguidas.
    """
    game, keys = wanted(snapshot, hold)
    fora: list[str] = []
    if game:
        fora += _diff(_read(client, GAME_SETTINGS), game, "interface")
    if keys:
        fora += _diff(_read(client, INPUT_SETTINGS), keys, "teclas")
    return fora


def _merge(base: dict, over: dict) -> dict:
    """Dois níveis, que é a profundidade que estas rotas têm."""
    saida = {b: dict(v) if isinstance(v, dict) else v for b, v in base.items()}
    for block, values in over.items():
        atual = saida.get(block)
        if isinstance(atual, dict) and isinstance(values, dict):
            atual.update(values)
        else:
            saida[block] = dict(values) if isinstance(values, dict) else values
    return saida


def _diff(live: dict, want: dict, label: str) -> list[str]:
    """Só o que o cliente devolveu, e devolveu diferente.

    Chave ausente da resposta não conta como divergência: o cliente
    omite o que está no padrão dele, e cobrar essas faria a conferência
    reprovar para sempre uma cópia que pegou.
    """
    fora: list[str] = []
    for block, values in want.items():
        atual = live.get(block)
        if isinstance(values, dict) and isinstance(atual, dict):
            fora += [
                f"{label}: {block}/{key}"
                for key, value in values.items()
                if key in atual and atual[key] != value
            ]
        elif block in live and live[block] != values:
            fora.append(f"{label}: {block}")
    return fora


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
        hold: Callable[[], dict] | None = None,
    ) -> None:
        self._client = client
        self._accounts = accounts
        self._save = save or (lambda: None)
        self._log = log or (lambda message: None)
        self._on_change = on_change or (lambda: None)
        self._now = now
        # O que outra parte do app está segurando na mesma rota agora.
        # Hoje é só o silêncio de antes da partida; a cópia pergunta
        # para não escrever por cima dele.
        self._hold = hold or (lambda: {})
        self._due: list[float] = []
        self._capture = ""
        self._apply_requested = False
        self._apply_target = ""
        # A LCU só representa uma conta de cada vez. Guardar a chave que a
        # vigia acabou de anunciar permite cancelar um clique que ficou na
        # fila enquanto o usuário trocava de conta, em vez de copiar os
        # controles no perfil errado.
        self._active_key = ""
        self._rounds = 0
        self._announced = False

    # -- pedidos de fora ------------------------------------------------

    def account_arrived(self, identity: Identity) -> None:
        """Outra conta entrou: agenda a cópia, se houver o que copiar."""
        key = account_key(identity)
        self._active_key = key
        if key == self._accounts.main:
            # A principal é o modelo; ela não recebe cópia de ninguém.
            self._due = []
            return
        if not self._accounts.main_game_settings():
            return
        agora = self._now()
        self._due = [agora + espera for espera in APPLY_DELAYS]
        self._rounds = 0
        self._announced = False
        self._log(
            "Configurações do jogo da conta principal serão aplicadas "
            "nesta conta em instantes."
        )

    def request_capture(self, key: str) -> None:
        """A janela pediu para guardar as configurações desta conta."""
        self._capture = key

    def request_apply(self, key: str = "") -> None:
        """A janela pediu para aplicar agora, sem esperar.

        ``key`` é conservada até o `tick`: a chamada vem da thread da GUI,
        mas a escrita acontece na thread que tem a LCU. Sem esse vínculo um
        clique antigo podia alcançar a conta que entrou logo depois.
        """
        self._apply_requested = True
        self._apply_target = key
        self._rounds = 0

    # -- trabalho -------------------------------------------------------

    def tick(self) -> None:
        """Uma volta do relógio da vigia: faz o que estiver na hora."""
        key, self._capture = self._capture, ""
        if key:
            if self._is_current(key):
                self._do_capture(key)
            else:
                self._log(
                    "A conta mudou antes de guardar os controles; o pedido antigo "
                    "foi cancelado."
                )
        asked, target = self._apply_requested, self._apply_target
        self._apply_requested = False
        self._apply_target = ""
        if asked:
            if target and not self._is_current(target):
                self._log(
                    "A conta mudou antes de aplicar os controles; o pedido antigo "
                    "foi cancelado."
                )
                return
            self._due = []
            self._do_apply(asked=True)
            return
        if self._due and self._now() >= self._due[0]:
            self._due.pop(0)
            self._do_apply()

    def _is_current(self, key: str) -> bool:
        """Verdadeiro quando a chave ainda é a conta que a LCU representa.

        A ausência de anúncio é aceita para compatibilidade com chamadas de
        inicialização e com o cliente ainda subindo; depois que a vigia já
        anunciou alguém, a igualdade passa a ser obrigatória.
        """
        return not self._active_key or key == self._active_key

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
        hold = self._held()
        try:
            written = apply(self._client, snapshot, hold)
        except LcuError as exc:
            self._log(f"Não consegui aplicar as configurações do jogo: {exc}")
            self._due = []
            return
        if not written:
            return
        self._rounds += 1
        try:
            fora = mismatches(self._client, snapshot, hold)
        except LcuError:
            # Sem leitura não há veredito. Vale o que sempre valeu: a
            # escrita foi aceita, e é isso que se conta.
            fora = []
        if fora and self._rounds < MAX_ROUNDS:
            # Ainda não grudou — o cliente costuma estar terminando de
            # baixar a conta que entrou. Marcar outra rodada é o que
            # antes o usuário fazia à mão, clicando no botão.
            self._due.append(self._now() + RETRY_DELAY)
            self._due.sort()
            if asked:
                self._log(
                    "Configurações enviadas, mas o cliente ainda não "
                    f"aceitou {len(fora)} ajuste(s). Tento de novo em "
                    "instantes — deixe o cliente na tela inicial."
                )
            return
        if fora:
            # Passou da conta de rodadas: o problema não é tempo, e
            # insistir daqui em diante só encheria o diário. O botão
            # da tela continua valendo para quem quiser tentar de novo.
            self._due = []
            self._log(
                "Apliquei as configurações da conta principal, mas o "
                f"cliente não aceitou {len(fora)} ajuste(s) "
                f"({', '.join(fora[:3])}). Confira dentro do jogo."
            )
            self._announced = True
            return
        # Uma vez por chegada de conta. O botão da tela fala sempre,
        # porque ali houve um clique esperando resposta.
        if self._announced and not asked:
            return
        self._announced = True
        self._log(
            "Configurações do jogo da conta principal aplicadas nesta conta "
            f"({' e '.join(written)}). Valem a partir da próxima partida."
        )

    def _held(self) -> dict:
        """O que não pode ser sobrescrito agora, se alguém estiver segurando."""
        try:
            segurado = self._hold()
        except Exception:  # noqa: BLE001 - a cópia não cai por causa disto
            return {}
        return segurado if isinstance(segurado, dict) else {}

    def _store(self) -> None:
        try:
            self._save()
        except OSError as exc:
            self._log(f"Não consegui gravar as contas: {exc}")
        # A tela mostra quem tem fotografia guardada, e quem gravou foi
        # esta thread. O aviso atravessa para a janela redesenhar.
        self._on_change()
