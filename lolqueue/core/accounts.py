"""Um perfil de ajustes para cada conta que já entrou neste PC.

O app tem uma configuração só, e ela é do computador — não de quem
está logado. Isso funciona enquanto é sempre a mesma pessoa. Deixa de
funcionar no instante em que o jogador entra na conta de outro: a lista
de campeões é a dele, a rota pedida é a dele, e o lado do Flash é o
dele, o que atrapalha a partida inteira de quem emprestou.

Aqui cada conta ganha o seu recorte da config, guardado à parte e
trocado sozinho quando o cliente diz quem entrou. Uma delas é marcada
como principal, e é dela que uma conta nunca vista herda tudo: quem
troca de conta quase sempre quer o mesmo app, não um app zerado. A
primeira conta que aparecer vira a principal sem perguntar nada — sem
isso a herança só começaria a valer depois de o usuário achar a tela.

O arquivo mora ao lado da config, e é gravado do mesmo jeito: inteiro
ou não gravado. Perdê-lo custa os perfis, não a config em uso.
"""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..config import Config, accounts_path
from .identity import Identity


def account_key(identity: Identity) -> str:
    """Chave estável da conta.

    Inclui a região porque o mesmo Riot ID existe em servidores
    diferentes, e são contas diferentes. Em minúsculas porque o cliente
    devolve o nome com a caixa que o jogador escolheu, e ele pode
    trocar a caixa sem trocar de conta.
    """
    return f"{identity.game_name}#{identity.tag_line}@{identity.region}".casefold()


def account_label(identity: Identity) -> str:
    """Como a conta aparece na tela, com a caixa que o dono escolheu."""
    return f"{identity.game_name}#{identity.tag_line}"


def settings_of(config: Config) -> dict:
    """Fotografia dos ajustes de agora, pronta para virar perfil."""
    return asdict(config)


def apply_settings(config: Config, settings: dict) -> None:
    """Despeja um perfil sobre a config em uso, no lugar.

    No lugar de propósito: a janela, o motor e a vigilância seguram
    todos a mesma instância de `Config`, e trocá-la por outra deixaria
    metade do app olhando para a config da conta anterior.

    Campo desconhecido é ignorado — um perfil gravado por uma versão
    mais nova não pode derrubar uma mais velha — e o que sobrou passa
    pelo mesmo saneamento da leitura de disco.
    """
    if not isinstance(settings, dict):
        return
    known = {f.name for f in fields(Config)}
    for name, value in settings.items():
        if name in known:
            setattr(config, name, value)
    config.sanitize()


@dataclass
class Account:
    """Uma conta lembrada e o que ela guarda."""

    label: str
    region: str = ""
    last_seen: str = ""
    settings: dict = field(default_factory=dict)
    #: As configurações de dentro do jogo — teclas, interface, câmera —
    #: como o cliente do LoL as devolve. Ficam à parte de `settings`
    #: porque não são do app: `settings` é a config daqui, e esta é uma
    #: fotografia do jogo, guardada só na conta que serve de modelo.
    game_settings: dict = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw) -> "Account | None":
        if not isinstance(raw, dict):
            return None
        label = raw.get("label")
        if not isinstance(label, str) or not label:
            return None
        settings = raw.get("settings")
        game = raw.get("game_settings")
        return cls(
            label=label,
            region=str(raw.get("region") or ""),
            last_seen=str(raw.get("last_seen") or ""),
            settings=settings if isinstance(settings, dict) else {},
            game_settings=game if isinstance(game, dict) else {},
        )


#: O que aconteceu quando a conta chegou, para quem chama poder contar
#: no registro. São três histórias diferentes e nenhuma é erro.
ARRIVED_KNOWN = "known"
ARRIVED_INHERITED = "inherited"
ARRIVED_FIRST = "first"


@dataclass(frozen=True)
class Arrival:
    """O desfecho de uma troca de conta."""

    key: str
    label: str
    kind: str
    #: De quem herdou, quando herdou. Vazio nos outros casos.
    source: str = ""
    #: Se esta conta é a principal.
    main: bool = False


class Accounts:
    """O histórico de contas e o perfil de cada uma."""

    def __init__(
        self,
        main: str = "",
        accounts: dict[str, Account] | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self.main = main
        self.accounts: dict[str, Account] = dict(accounts or {})
        self._now = now or (lambda: datetime.now().isoformat(timespec="seconds"))
        # Duas threads gravam este arquivo: a janela, quando o usuário
        # mexe nos ajustes, e a vigia da conexão, quando copia as
        # configurações do jogo. A gravação já é inteira-ou-nada; o
        # cadeado impede que uma troque o `.part` da outra no meio.
        # `save` também usa este cadeado; ele precisa ser reentrante porque
        # uma troca de principal pode preparar o modelo e em seguida ser
        # persistida na mesma passagem da GUI. O arquivo pertence às duas
        # threads (janela e vigia do cliente), não a uma delas só.
        self._lock = threading.RLock()
        if self.main not in self.accounts:
            self.main = ""

    # -- disco ----------------------------------------------------------

    @classmethod
    def load(
        cls, path: Path | None = None, now: Callable[[], str] | None = None
    ) -> "Accounts":
        """Lê os perfis. Ausente ou corrompido começa vazio.

        Vazio é um estado normal — é como todo mundo começa —, então um
        arquivo ilegível não tem por que virar erro na cara do usuário:
        a primeira conta a aparecer refaz o histórico.
        """
        target = path or accounts_path()
        try:
            raw = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return cls(now=now)
        if not isinstance(raw, dict):
            return cls(now=now)
        found: dict[str, Account] = {}
        stored = raw.get("accounts")
        for key, value in (stored if isinstance(stored, dict) else {}).items():
            account = Account.from_raw(value)
            if isinstance(key, str) and key and account is not None:
                found[key] = account
        main = raw.get("main")
        return cls(main=main if isinstance(main, str) else "", accounts=found, now=now)

    def save(self, path: Path | None = None) -> None:
        """Grava os perfis, inteiros ou não grava. Ver `Config.save`."""
        target = path or accounts_path()
        with self._lock:
            # O retrato precisa nascer dentro do cadeado. Antes, uma
            # atualização do modelo pela thread do cliente podia acontecer
            # enquanto a compreensão percorria o dicionário e deixar o
            # `contas.json` incompleto (ou levantar RuntimeError).
            payload = {
                "main": self.main,
                "accounts": {
                    key: asdict(account) for key, account in self.accounts.items()
                },
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".part")
            try:
                temp.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                temp.replace(target)
            except OSError:
                temp.unlink(missing_ok=True)
                raise

    # -- uso ------------------------------------------------------------

    def arrive(self, identity: Identity, config: Config) -> Arrival:
        """Uma conta entrou: alinha a config com o perfil dela.

        Conhecida devolve o que era dela. Nova herda da principal —
        inteira, porque quem pega a conta emprestada quer o mesmo app,
        não um app zerado. Nova sem principal alguma vira ela mesma a
        principal, guardando o que já estava na tela: é o caso de quem
        usa o app há meses e só agora ganhou perfis.
        """
        key = account_key(identity)
        label = account_label(identity)
        with self._lock:
            known = self.accounts.get(key)
            source = ""
            if known is not None:
                apply_settings(config, known.settings)
                kind = ARRIVED_KNOWN
            else:
                parent = self.accounts.get(self.main)
                if parent is not None:
                    apply_settings(config, parent.settings)
                    kind = ARRIVED_INHERITED
                    source = parent.label
                else:
                    kind = ARRIVED_FIRST
                self.accounts[key] = Account(label=label, region=identity.region)
            account = self.accounts[key]
            account.label = label
            account.region = identity.region
            account.last_seen = self._now()
            account.settings = settings_of(config)
            if not self.main:
                self.main = key
            return Arrival(
                key=key, label=label, kind=kind, source=source, main=key == self.main
            )

    def remember(self, key: str, config: Config) -> bool:
        """Guarda no perfil da conta o que a config tem agora.

        Chamado a cada mexida nos ajustes. Conta desconhecida não vira
        conta nova aqui: sem o cliente aberto não há como saber o nome
        nem a região, e um perfil sem dono seria lixo permanente.
        """
        with self._lock:
            account = self.accounts.get(key)
            if account is None:
                return False
            account.settings = settings_of(config)
            return True

    def set_main(self, key: str) -> bool:
        """Marca a conta principal sem deixar o modelo de jogo desaparecer.

        O modelo de controles é uma fotografia escolhida pelo usuário, não
        uma particularidade do nome que antes era principal. Se a nova
        principal ainda não tem fotografia própria, ela recebe uma cópia do
        modelo atual; se já tem, a fotografia dela vence. Isso evita que um
        simples ``Tornar principal`` desligue silenciosamente a cópia entre
        contas.
        """
        with self._lock:
            if key not in self.accounts:
                return False
            if key == self.main:
                return True
            previous = self.main
            previous_account = self.accounts.get(previous)
            target = self.accounts[key]
            if previous_account is not None and previous_account.game_settings:
                if not target.game_settings:
                    target.game_settings = deepcopy(previous_account.game_settings)
                # Só a principal deve carregar a etiqueta de modelo. A cópia
                # acima é profunda para um futuro PATCH nunca editar o perfil
                # antigo por referência.
                previous_account.game_settings = {}
            self.main = key
            return True

    def set_game_settings(self, key: str, snapshot: dict) -> bool:
        """Guarda na conta a fotografia das configurações do jogo.

        Fotografia vazia apaga a que havia: é assim que o usuário
        desliga a cópia sem esquecer a conta inteira.
        """
        with self._lock:
            account = self.accounts.get(key)
            if account is None:
                return False
            account.game_settings = deepcopy(snapshot or {})
            return True

    def game_settings_of(self, key: str) -> dict:
        """O que a conta guardou do jogo. Vazio se não guardou nada."""
        with self._lock:
            account = self.accounts.get(key)
            return deepcopy(account.game_settings) if account is not None else {}

    def main_game_settings(self) -> dict:
        """O modelo a copiar: o que a conta principal guardou."""
        with self._lock:
            return self.game_settings_of(self.main) if self.main else {}

    def forget(self, key: str) -> bool:
        """Tira uma conta do histórico.

        Apagar a principal deixa o posto vago em vez de escolher outra
        no lugar: herdar da conta errada é pior do que não herdar.
        """
        with self._lock:
            if self.accounts.pop(key, None) is None:
                return False
            if self.main == key:
                self.main = ""
            return True

    def ordered(self) -> list[tuple[str, Account]]:
        """As contas da mais recente para a mais antiga, principal antes.

        A principal na frente porque é a que o usuário procura quando
        abre a tela — para conferir, ou para passar o posto adiante.
        """

        def rank(item: tuple[str, Account]):
            key, account = item
            return (key != self.main, _newest_first(account.last_seen), account.label)

        with self._lock:
            # A GUI só precisa desenhar valores. Devolver cópias faz com que
            # a thread da vigia não consiga mudar uma etiqueta no meio do
            # desenho de uma linha.
            return [
                (key, deepcopy(account))
                for key, account in sorted(self.accounts.items(), key=rank)
            ]

    def __len__(self) -> int:
        with self._lock:
            return len(self.accounts)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self.accounts


def _newest_first(text: str) -> tuple[int, str]:
    """Ordena datas ISO da mais nova para a mais velha.

    Sem data vai para o fim: é conta de um arquivo escrito à mão ou de
    uma versão anterior, e não há como saber quando foi vista.
    """
    return (0, _flip(text)) if text else (1, "")


def _flip(text: str) -> str:
    """Inverte a ordem alfabética de um texto, caractere a caractere."""
    return "".join(chr(0x10FFFF - ord(char)) for char in text)
