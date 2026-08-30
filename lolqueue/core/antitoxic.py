"""Silenciar chat e emotes antes da partida começar.

Mutar depois que a primeira ofensa chegou já é tarde: você leu. O único
momento em que o silêncio funciona é antes de entrar, e o cliente abre
justamente aí uma janela para escrever nas opções do jogo — a seleção de
campeão, quando a partida ainda não carregou.

A primeira versão daqui mexia só em `ShowAlliedChat`, `ShowAllChannelChat`
e `HideEnemySummonerEmotes`, e o jogador relatou que continuava vendo
tudo. As três chaves são reais, o PATCH era aceito e chegava ao disco em
menos de um segundo — conferido no `game.cfg` — mas elas escondem
*janelas*, não desligam o chat. Quem desliga é `EnableChat`, na seção
`Chat`: ela não aparece na leitura do cliente, só no `game.cfg`, e por
isso tinha passado despercebida. O silêncio agora vai pelas duas portas.

O que dá para desligar, e o que não dá:

- **Chat inteiro** (`Chat.EnableChat`): aliado, geral e o do inimigo, de
  uma vez. Em troca, você também não escreve — que é o ponto de um
  anti-tilt.
- **A janela do chat** (`ChatChannelVisibility`) e os canais um a um,
  como reforço para o caso de a chave mestra falhar num patch futuro.
- **Emotes dos inimigos** também.
- **Emotes dos aliados** o jogo não expõe. Existe `EmotePopupUIDisplayMode`
  nas mesmas opções, mas ela é a roda de emotes do próprio jogador — o
  jeito de *você* abrir o menu, não o de ver os outros. Mexer nela
  atrapalharia o jogador em vez de proteger. Fica de fora, de propósito.

Nada aqui é definitivo: `apply` guarda o valor anterior de cada chave e
`restore` devolve tudo como estava.
"""

from __future__ import annotations

from typing import Any, Callable

from ..lcu import endpoints
from ..lcu.client import LcuError

#: A seção que o cliente devolve na leitura e onde vive a maior parte do
#: que interessa. Sem ela, a resposta não é um cliente que dá para mexer.
SECTION = "HUD"

#: O que "mudo" significa, seção por seção. Os nomes são do jogo; o
#: valor é o que desliga.
MUTED: dict[str, dict[str, Any]] = {
    "Chat": {"EnableChat": False},
    SECTION: {
        "ShowAlliedChat": False,
        "ShowAllChannelChat": False,
        "HideEnemySummonerEmotes": True,
        "ChatChannelVisibility": 0,
    },
}

#: O que o jogo usa quando ninguém mexeu, para as chaves que a leitura do
#: cliente não devolve. Só entra em cena se o `game.cfg` também não
#: responder — devolver o chat ligado erra menos que deixá-lo mudo.
GAME_DEFAULTS: dict[str, dict[str, Any]] = {"Chat": {"EnableChat": True}}


def _disk_flag(name: str, default: bool) -> bool:
    """O valor de uma chave booleana no `game.cfg`.

    A leitura do cliente não devolve a seção `Chat` — aceita escrever
    nela, mas não a mostra. O arquivo em disco mostra, e é a única forma
    de saber o que o jogador tinha antes de mexermos. O import é tardio
    de propósito: `core` não carrega `vision` para ler uma linha de
    texto, e se o arquivo não estiver onde se espera, o padrão do jogo
    responde.
    """
    try:
        from ..vision.gamecfg import read_flag
    except Exception:  # pragma: no cover - depende da instalação do jogo
        return default
    return read_flag(name, default=default)


class MuteGuard:
    """Aplica e desfaz o silêncio nas opções do jogo.

    Guarda em memória o que encontrou antes de mexer, para que desmarcar
    a opção devolva exatamente o que o jogador tinha — e não um padrão
    inventado por nós.
    """

    def __init__(
        self,
        client,
        config,
        log: Callable[[str], None] | None = None,
        read_flag: Callable[[str, bool], bool] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._log = log or (lambda message: None)
        self._read_flag = read_flag or _disk_flag
        self._original: dict[str, dict[str, Any]] | None = None
        # Sem isto, cada tick da seleção mandaria o mesmo PATCH.
        self._applied = False
        # Se o jogo está mudo agora — por obra nossa ou porque já
        # estava. Ver `forced`: é isto, e não `_original`, que diz o
        # que ninguém mais pode escrever por cima.
        self._silent = False

    @property
    def applied(self) -> bool:
        return self._applied

    def reset(self) -> None:
        """Esquece que já agiu, sem tocar nas opções.

        Chamado quando a seleção acaba: a próxima partida volta a ter
        direito de aplicar. O que foi guardado continua guardado, porque
        `restore` ainda pode ser chamado depois.
        """
        self._applied = False

    def apply(self) -> bool:
        """Deixa o jogo mudo. Devolve se chegou a mudar alguma coisa."""
        if not getattr(self._config, "mute_before_game", False):
            # Desmarcar no meio da seleção devolve na hora, sem esperar
            # o fim da partida: quem desligou quer o chat de volta já.
            self.restore()
            return False
        if self._applied:
            return False
        self._applied = True

        atual = self._read()
        if atual is None:
            return False

        # Só mandar o que está diferente: um PATCH que não muda nada é
        # ruído no cliente e ainda apagaria o registro do original.
        mudanca: dict[str, dict[str, Any]] = {}
        for secao, chaves in MUTED.items():
            atuais = atual.get(secao, {})
            diferente = {k: v for k, v in chaves.items() if atuais.get(k) != v}
            if diferente:
                mudanca[secao] = diferente
        if not mudanca:
            self._silent = True
            self._log("Chat e emotes já estavam no silêncio.")
            return False

        if self._original is None:
            guardado = {
                secao: {
                    chave: atual[secao][chave]
                    for chave in diferente
                    if chave in atual.get(secao, {})
                }
                for secao, diferente in mudanca.items()
            }
            self._original = {s: v for s, v in guardado.items() if v}

        if not self._write(mudanca):
            return False
        self._silent = True
        self._log(
            "Silêncio ligado antes da partida: "
            f"{', '.join(sorted(_keys(mudanca)))}."
        )
        return True

    def forced(self) -> dict[str, dict[str, Any]]:
        """O que o silêncio está segurando agora, para quem escreve depois.

        A cópia das configurações da conta principal usa exatamente
        esta rota (`GAME_SETTINGS`) e manda o bloco inteiro — inclusive
        as chaves de chat, no valor ligado que a conta principal tinha.
        Chegando depois do silêncio, ela devolvia o chat aliado e os
        emotes do inimigo sem que uma linha do diário dissesse por quê,
        e o `_applied` daqui ainda impedia o silêncio de voltar: o jogo
        ficava meio mudo pelo resto da partida. Quem escreve por cima
        pergunta antes o que não pode mexer.

        Quem responde é `_silent`, e não `_applied` nem `_original`.
        `_applied` dura menos que o silêncio — `reset` o limpa quando a
        seleção acaba, e a partida, que é onde o chat incomoda, começa
        depois disso. E `_original` guarda só o que *mudou*: num jogador
        que já jogava com o chat de aliado desligado, essa chave não
        estaria ali, e a cópia a religaria justamente para quem tinha
        pedido silêncio primeiro. O silêncio inteiro é indivisível.
        """
        if not self._silent:
            return {}
        return {secao: dict(chaves) for secao, chaves in MUTED.items()}

    def restore(self) -> bool:
        """Devolve as opções como estavam antes do primeiro `apply`."""
        # Sai do ar antes de qualquer saída: mesmo quando não há o que
        # reescrever, o silêncio acabou e ninguém mais precisa respeitá-lo.
        self._silent = False
        if not self._original:
            return False
        anterior = self._original
        self._original = None
        self._applied = False
        if not self._write(anterior):
            return False
        self._log("Silêncio desligado: chat e emotes voltaram ao normal.")
        return True

    def _read(self) -> dict[str, dict[str, Any]] | None:
        """O valor atual de cada chave que vamos mexer, por seção.

        O que o cliente devolve vale mais que o disco; o disco só entra
        onde o cliente é omisso.
        """
        try:
            settings = self._client.get(endpoints.GAME_SETTINGS)
        except LcuError:
            return None
        if not isinstance(settings, dict):
            return None
        principal = settings.get(SECTION)
        if not isinstance(principal, dict):
            # Sem a seção que o cliente sempre devolve, a resposta não é
            # de um cliente pronto — melhor tentar de novo no próximo tick.
            return None

        atual: dict[str, dict[str, Any]] = {}
        for secao, chaves in MUTED.items():
            vindo = settings.get(secao)
            conhecido = dict(vindo) if isinstance(vindo, dict) else {}
            padrao = GAME_DEFAULTS.get(secao, {})
            for chave in chaves:
                if chave not in conhecido and chave in padrao:
                    conhecido[chave] = self._read_flag(chave, bool(padrao[chave]))
            atual[secao] = conhecido
        return atual

    def _write(self, valores: dict[str, dict[str, Any]]) -> bool:
        try:
            self._client.patch(endpoints.GAME_SETTINGS, json=valores)
        except LcuError:
            # Recusa do cliente não é motivo para derrubar a seleção; o
            # pior caso é o jogador ver o chat, que é o que já acontecia.
            return False
        return True


def _keys(mudanca: dict[str, dict[str, Any]]) -> list[str]:
    return [chave for chaves in mudanca.values() for chave in chaves]
