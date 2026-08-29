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

    @classmethod
    def from_raw(cls, raw) -> "Account | None":
        if not isinstance(raw, dict):
            return None
        label = raw.get("label")
        if not isinstance(label, str) or not label:
            return None
        settings = raw.get("settings")
        return cls(
            label=label,
            region=str(raw.get("region") or ""),
            last_seen=str(raw.get("last_seen") or ""),
            settings=settings if isinstance(settings, dict) else {},
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
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "main": self.main,
            "accounts": {
                key: asdict(account) for key, account in self.accounts.items()
            },
        }
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
        account = self.accounts.get(key)
        if account is None:
            return False
        account.settings = settings_of(config)
        return True

    def set_main(self, key: str) -> bool:
        """Marca a conta principal. Chave desconhecida não marca nada."""
        if key not in self.accounts:
            return False
        self.main = key
        return True

    def forget(self, key: str) -> bool:
        """Tira uma conta do histórico.

        Apagar a principal deixa o posto vago em vez de escolher outra
        no lugar: herdar da conta errada é pior do que não herdar.
        """
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

        return sorted(self.accounts.items(), key=rank)

    def __len__(self) -> int:
        return len(self.accounts)

    def __contains__(self, key: object) -> bool:
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
