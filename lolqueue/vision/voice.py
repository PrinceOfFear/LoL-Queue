"""Dizer o aviso em voz alta, com dicção que dê para entender.

As vozes que o Windows instala em português — Maria, Daniel — são as
robóticas do SAPI, e um aviso que o jogador precisa entender em meio
segundo, no meio de uma luta, não pode ser dito assim. A voz aqui é
sempre neural, sintetizada pelo serviço da Microsoft através do
`edge-tts`; não existe queda para o SAPI, porque um aviso que não se
entende é pior que silêncio — rouba atenção e não entrega nada.

O problema óbvio dessa escolha é a latência: sintetizar pela rede leva
algo entre trezentos e oitocentos milissegundos, e o inimigo já terá
chegado. A saída é que o conjunto de frases possíveis é pequeno e
conhecido cedo — um campeão, uma dezena de lugares no mapa e três tons.
Assim que se sabe quem é o jungler inimigo dá para sintetizar tudo de
uma vez, guardar em disco e, na hora do aviso, apenas tocar o arquivo. O
cache sobrevive entre partidas, então o mesmo campeão na próxima vez já
vem pronto.

O áudio toca pelo MCI, que é parte do Windows e lê mp3 direto: uma
biblioteca de áudio a mais no executável seria pagar caro para tocar
arquivos de dois segundos.

Se a rede não responder, o aviso não sai e o diário registra a falha uma
vez só — um recado por frase seria spam.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

#: As vozes que a interface oferece, das melhores para as piores de
#: entender. As multilíngues vêm primeiro de propósito: são a geração
#: nova do serviço e, mais importante aqui, pronunciam nome de campeão
#: sem mastigar. A palavra que o jogador não pode perder no aviso é
#: justamente o nome, e ele quase sempre vem do inglês — as vozes
#: antigas, presas ao português, transformam "Kha'Zix" e "Warwick" em
#: ruído bem no meio da frase.
VOICES = (
    "pt-BR-ThalitaMultilingualNeural",
    "en-US-AndrewMultilingualNeural",
    "en-US-BrianMultilingualNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-AvaMultilingualNeural",
    "pt-BR-AntonioNeural",
    "pt-BR-FranciscaNeural",
)

DEFAULT_VOICE = VOICES[0]

#: Nome de cada voz na interface. O identificador do serviço não diz
#: nada a quem vai escolher; o sotaque, sim.
VOICE_LABELS = {
    "pt-BR-ThalitaMultilingualNeural": "Thalita — brasileira, feminina",
    "en-US-AndrewMultilingualNeural": "Andrew — sotaque leve, masculina",
    "en-US-BrianMultilingualNeural": "Brian — sotaque leve, masculina",
    "en-US-EmmaMultilingualNeural": "Emma — sotaque leve, feminina",
    "en-US-AvaMultilingualNeural": "Ava — sotaque leve, feminina",
    "pt-BR-AntonioNeural": "Antônio — brasileira, masculina (antiga)",
    "pt-BR-FranciscaNeural": "Francisca — brasileira, feminina (antiga)",
}

#: Quantas frases sintetizar ao mesmo tempo na preparação. O gargalo é a
#: viagem de rede, não a máquina; algumas em paralelo cortam a espera
#: sem parecer um ataque ao serviço.
PRIME_WORKERS = 3

#: Recado da falha, dito uma vez por sessão. São dois porque as duas
#: causas pedem coisas diferentes de quem lê: uma se resolve com um
#: comando, a outra é esperar a rede voltar. Um recado único mandaria
#: metade das pessoas procurar problema de rede que não existe.
SILENT_NOTICE = "Voz indisponível: sem resposta do sintetizador, os avisos ficam mudos."
MISSING_PACKAGE_NOTICE = (
    "Voz indisponível: o pacote edge-tts não está instalado neste Python — "
    "o aviso do jungler fica mudo a partida inteira. Instale com "
    "py -m pip install edge-tts e reabra o app."
)

_alias = itertools.count(1)


def cache_dir() -> Path:
    """Onde os mp3 ficam, ao lado do resto do que o app guarda."""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LoLQueue" / "voz"


def normalize_voice(name: str | None) -> str:
    """A voz pedida, se existir; senão a padrão.

    Config vem de arquivo editável à mão, e um nome inventado não pode
    calar o aviso.
    """
    return name if name in VOICES else DEFAULT_VOICE


# --- as duas operações que tocam o sistema -----------------------------


def synthesize(text: str, voice: str) -> bytes | None:
    """O mp3 da frase, pelo serviço neural. `None` se não deu.

    O import é tardio para que a falta do pacote não impeça o app de
    abrir — mas abrir é tudo o que ele faz sem o pacote. Não existe
    queda para voz local aqui, e o comentário que dizia existir custou
    a uma máquina inteira uma investigação: o app subia, a partida
    rodava, e nenhum aviso saía. Quem chama distingue os dois casos
    por `synthesizer_available()`.
    """
    try:
        import edge_tts

        dados = bytearray()
        for pedaco in edge_tts.Communicate(text, voice).stream_sync():
            if pedaco.get("type") == "audio":
                dados += pedaco.get("data") or b""
    except Exception:
        return None
    return bytes(dados) or None


def synthesizer_available() -> bool:
    """Se o sintetizador sequer pode ser carregado nesta máquina.

    Separa "o pacote não está aqui" de "a rede não respondeu". As duas
    emudecem o aviso igual, mas só a primeira tem conserto imediato.
    """
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return False
    return True


def play_file(path: Path) -> bool:
    """Toca um mp3 pelo MCI, esperando terminar.

    Espera de propósito: quem chama é a thread da fala, e duas frases
    sobrepostas não se entendem.
    """
    try:
        import ctypes

        winmm = ctypes.windll.winmm
    except Exception:
        return False

    nome = f"lolqueue{next(_alias)}"

    def comando(texto: str) -> int:
        return int(winmm.mciSendStringW(texto, None, 0, None))

    if comando(f'open "{path}" type mpegvideo alias {nome}') != 0:
        return False
    try:
        return comando(f"play {nome} wait") == 0
    finally:
        comando(f"close {nome}")


Synthesizer = Callable[[str, str], "bytes | None"]
Player = Callable[[Path], bool]


class Voice:
    """A fala do app: uma frase por vez, nunca na thread de quem pede.

    Rede e áudio entram injetados, para que os testes não precisem de
    nenhum dos dois.
    """

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        directory: Path | None = None,
        synth: Synthesizer | None = None,
        play: Player | None = None,
        on_message: Callable[[str], None] | None = None,
    ) -> None:
        self._voice = normalize_voice(voice)
        self._dir = Path(directory) if directory is not None else cache_dir()
        self._synth = synth or synthesize
        self._play = play or play_file
        self._on_message = on_message
        self._avisou = False

        self._fila: queue.Queue = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=PRIME_WORKERS)
        self._cond = threading.Condition()
        self._pendentes = 0
        self._closed = False

        self._thread = threading.Thread(
            target=self._loop, name="lolqueue-voz", daemon=True
        )
        self._thread.start()

    # -- estado ---------------------------------------------------------

    @property
    def voice(self) -> str:
        return self._voice

    @property
    def directory(self) -> Path:
        return self._dir

    @property
    def closed(self) -> bool:
        return self._closed

    def path_for(self, text: str) -> Path:
        """O arquivo daquela frase naquela voz.

        A voz entra no nome porque trocar de voz tem que trocar de
        áudio, e não reaproveitar o da anterior.
        """
        digest = hashlib.sha1(f"{self._voice}\n{text}".encode("utf-8")).hexdigest()
        return self._dir / f"{digest[:20]}.mp3"

    # -- contagem de trabalho pendente ----------------------------------

    def _begin(self) -> None:
        with self._cond:
            self._pendentes += 1

    def _end(self) -> None:
        with self._cond:
            self._pendentes -= 1
            self._cond.notify_all()

    def drain(self, timeout: float = 5.0) -> bool:
        """Espera acabar o que está na fila. Existe para os testes."""
        limite = time.monotonic() + timeout
        with self._cond:
            while self._pendentes > 0:
                restante = limite - time.monotonic()
                if restante <= 0:
                    return False
                self._cond.wait(restante)
        return True

    # -- síntese --------------------------------------------------------

    def _cached(self, text: str) -> Path | None:
        caminho = self.path_for(text)
        try:
            # Tamanho zero é download interrompido, não áudio.
            if caminho.is_file() and caminho.stat().st_size > 0:
                return caminho
        except OSError:
            pass
        return None

    def _ensure(self, text: str) -> Path | None:
        """O arquivo da frase, do disco ou recém-sintetizado."""
        pronto = self._cached(text)
        if pronto is not None:
            return pronto

        try:
            dados = self._synth(text, self._voice)
        except Exception:
            # Síntese é rede: qualquer coisa pode vir de lá, e nada disso
            # pode subir para a thread da fala.
            dados = None
        if not dados:
            return None

        caminho = self.path_for(text)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            temp = caminho.with_name(caminho.name + ".part")
            temp.write_bytes(dados)
            temp.replace(caminho)
        except OSError:
            return None
        return caminho

    def prime(self, phrases: Iterable[str | None]) -> int:
        """Sintetiza de antemão tudo o que a partida pode precisar dizer.

        É esta chamada que torna o aviso instantâneo: quando o jungler
        aparecer, o mp3 já está no disco. Devolve quantas frases entraram
        na fila.
        """
        if self._closed:
            return 0

        vistos: set[str] = set()
        pedidos = []
        for frase in phrases or ():
            texto = (frase or "").strip()
            if not texto or texto in vistos:
                continue
            vistos.add(texto)
            if self._cached(texto) is None:
                pedidos.append(texto)

        for texto in pedidos:
            self._begin()
            try:
                self._pool.submit(self._prime_one, texto)
            except RuntimeError:
                # Pool já encerrado por um `close` concorrente.
                self._end()
        return len(pedidos)

    def _prime_one(self, text: str) -> None:
        try:
            if self._ensure(text) is None:
                # A preparação é o primeiro contato com o serviço; se ela
                # falha, o jogador merece saber antes do gank, e não
                # descobrir pelo silêncio no meio dele.
                self._notify()
        finally:
            self._end()

    # -- fala -----------------------------------------------------------

    def say(self, text: str | None) -> bool:
        """Enfileira a frase. Volta na hora, sem esperar o áudio.

        O laço de captura chama isto; esperar a fala terminar cegaria o
        app por dois segundos, justamente durante o gank.
        """
        texto = (text or "").strip()
        if not texto or self._closed:
            return False
        self._begin()
        self._fila.put(texto)
        return True

    def _loop(self) -> None:
        while True:
            texto = self._fila.get()
            if texto is None:
                self._fila.task_done()
                return
            try:
                self._speak(texto)
            except Exception:
                # Uma frase perdida não pode derrubar a voz da partida
                # inteira.
                pass
            finally:
                self._fila.task_done()
                self._end()

    def _speak(self, text: str) -> None:
        caminho = self._ensure(text)
        if caminho is not None:
            try:
                if self._play(caminho):
                    return
            except Exception:
                pass
        # Sem áudio o aviso se perde. Cala a boca e conta no diário.
        self._notify()

    def _notify(self) -> None:
        if self._avisou or self._on_message is None:
            return
        self._avisou = True
        try:
            recado = (
                SILENT_NOTICE if synthesizer_available() else MISSING_PACKAGE_NOTICE
            )
            self._on_message(recado)
        except Exception:
            pass

    # -- encerramento ---------------------------------------------------

    def close(self) -> None:
        """Para de aceitar frases e devolve a thread. Pode ser repetido."""
        if self._closed:
            return
        self._closed = True
        self._fila.put(None)
        self._pool.shutdown(wait=False)
        self._thread.join(timeout=2.0)
