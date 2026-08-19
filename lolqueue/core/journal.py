"""Registro das mensagens do app em arquivo.

O painel da janela guarda umas centenas de linhas em memória e some
quando o app fecha — mas é ele que diz qual lista o motor usou, se o
banimento entrou e se a fila travou. Quem quer conferir isso quer
depois da partida, exatamente quando não havia mais nada para ler.

Um arquivo por dia, podados os antigos. Gravar é conveniência: qualquer
falha de disco desliga o registro em silêncio em vez de derrubar a
janela junto.
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

#: Quantos dias de registro ficam guardados. Sem poda o diretório
#: cresceria para sempre num app que roda todo dia.
KEEP_DAYS = 14

#: Nome de arquivo do registro: só o que casar com isto é podado, para
#: que nada mais que estiver na pasta seja apagado por engano.
FILE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.log$")


def _clock() -> str:
    return time.strftime("%H:%M:%S")


class Journal:
    """Grava mensagens no arquivo do dia."""

    def __init__(
        self,
        directory: Path,
        keep_days: int = KEEP_DAYS,
        clock: Callable[[], str] = _clock,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._directory = Path(directory)
        self._keep_days = keep_days
        self._clock = clock
        self._today = today
        #: Desliga o registro depois da primeira falha. Insistir a cada
        #: linha travaria a janela inteira num disco doente.
        self.failed = False
        self._prune()

    @property
    def directory(self) -> Path:
        return self._directory

    def path_for(self, day: date) -> Path:
        return self._directory / f"{day.isoformat()}.log"

    def write(self, message: str) -> None:
        if self.failed:
            return
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            target = self.path_for(self._today())
            with target.open("a", encoding="utf-8") as handle:
                handle.write(f"{self._clock()}  {message}\n")
        except OSError:
            self.failed = True

    def _prune(self) -> None:
        """Apaga o que passou de `keep_days`, só entre os arquivos nossos."""
        try:
            entries = list(self._directory.iterdir())
        except OSError:
            return
        cutoff = self._today() - timedelta(days=self._keep_days)
        for entry in entries:
            match = FILE_PATTERN.match(entry.name)
            if match is None:
                continue
            try:
                day = date(*(int(part) for part in match.groups()))
            except ValueError:
                continue
            if day < cutoff:
                try:
                    entry.unlink()
                except OSError:
                    pass
