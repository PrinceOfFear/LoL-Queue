"""Liga e desliga a vigilância do jungler inteira — voz inclusive.

O `JungleWatcher` olha o minimapa e a `Voice` fala; as duas seguram
recursos caros: uma thread de captura de tela e uma thread de áudio com
um pool de síntese atrás. Deixar as duas de pé o app inteiro seria
pagar por elas nas horas em que ninguém está jogando.

Então nascem na partida e morrem com ela. O efeito colateral é o que
mais importa para quem usa: trocar a voz nas configurações passa a valer
na partida seguinte, sem religar o app — a voz é lida no momento de
ligar, não no de construir.

Para o motor, isto aqui é só um `start`/`stop`.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .voice import MISSING_PACKAGE_NOTICE, normalize_voice, synthesizer_available


class JungleSession:
    """A vigilância como um interruptor só, com o que ela usa por dentro."""

    def __init__(
        self,
        config,
        log: Callable[[str], None] | None = None,
        build: Callable[[str], tuple[Any, Any]] | None = None,
    ) -> None:
        self._config = config
        self._log = log or (lambda message: None)
        self._build = build or self._default_build
        self._watcher: Any | None = None
        self._voice: Any | None = None
        # Ligar e desligar chegam de threads diferentes: a vigilância de
        # fase acende a partida assim que o cliente entra em jogo, e o
        # fechamento do app apaga tudo pela thread da janela. As duas
        # caindo juntas — fechar o app exatamente na transição para "em
        # jogo" — deixavam um `JungleWatcher` órfão capturando tela e uma
        # `Voice` de pé depois do app fechado, ou seja, um processo que
        # não morre. O ferrolho faz uma esperar a outra terminar.
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._watcher is not None

    def start(self) -> bool:
        """Abre a vigilância. Chamar de novo enquanto roda não faz nada."""
        with self._lock:
            return self._start()

    def _start(self) -> bool:
        if self._watcher is not None:
            return False
        nome = normalize_voice(getattr(self._config, "jungle_voice", None))
        try:
            watcher, voice = self._build(nome)
        except Exception as erro:  # pragma: no cover - depende do ambiente
            # Sem tela, sem rede ou sem áudio o aviso simplesmente não
            # existe nesta partida. Nada disso justifica derrubar o app
            # no meio de um jogo.
            self._log(f"Não deu para ligar o aviso do jungler: {erro}")
            return False
        self._watcher, self._voice = watcher, voice
        self._warn_if_mute()
        watcher.start()
        return True

    def _warn_if_mute(self) -> None:
        """Diz na hora de ligar quando nenhuma palavra vai sair.

        Sem o pacote de síntese a vigilância roda inteira, acha o
        jungler, acerta o canto do mapa — e não fala. A queixa só
        apareceria na primeira fala perdida, ou seja, no meio do gank
        que ela deveria ter avisado. Aqui ela sai antes da partida,
        quando ainda dá tempo de instalar o pacote.
        """
        if not synthesizer_available():
            self._log(MISSING_PACKAGE_NOTICE)

    def stop(self) -> None:
        """Fecha tudo o que a partida abriu, na ordem certa."""
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        watcher, voice = self._watcher, self._voice
        self._watcher = self._voice = None
        if watcher is not None:
            # Primeiro o laço: parado ele, ninguém mais pede fala.
            watcher.stop()
        if voice is not None:
            voice.close()

    def _default_build(self, voice_name: str) -> tuple[Any, Any]:
        # Import tardio: abrir o app não deveria carregar numpy e o
        # resto do maquinário de visão por causa de um recurso que o
        # jogador pode ter desligado.
        from .voice import Voice
        from .watcher import JungleWatcher

        voice = Voice(voice_name, on_message=self._log)
        return JungleWatcher(voice, on_message=self._log), voice
