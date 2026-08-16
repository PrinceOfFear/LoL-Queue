from __future__ import annotations

from enum import Enum


class GameflowPhase(str, Enum):
    NONE = "None"
    LOBBY = "Lobby"
    MATCHMAKING = "Matchmaking"
    CHECKED_INTO_TOURNAMENT = "CheckedIntoTournament"
    READY_CHECK = "ReadyCheck"
    CHAMP_SELECT = "ChampSelect"
    GAME_START = "GameStart"
    FAILED_TO_LAUNCH = "FailedToLaunch"
    IN_PROGRESS = "InProgress"
    RECONNECT = "Reconnect"
    WAITING_FOR_STATS = "WaitingForStats"
    PRE_END_OF_GAME = "PreEndOfGame"
    END_OF_GAME = "EndOfGame"
    TERMINATED_IN_ERROR = "TerminatedInError"
    UNKNOWN = "Unknown"

    @classmethod
    def parse(cls, raw: object) -> "GameflowPhase":
        """Traduz a resposta da API. Fase desconhecida vira UNKNOWN.

        A Riot adiciona fases entre patches; nenhuma delas pode derrubar
        o app.
        """
        try:
            return cls(raw)
        except ValueError:
            return cls.UNKNOWN


PLAYING_PHASES = frozenset(
    {
        GameflowPhase.GAME_START,
        GameflowPhase.IN_PROGRESS,
        GameflowPhase.RECONNECT,
    }
)

END_PHASES = frozenset(
    {
        GameflowPhase.WAITING_FOR_STATS,
        GameflowPhase.PRE_END_OF_GAME,
        GameflowPhase.END_OF_GAME,
    }
)


class PhaseTracker:
    """Converte polling contínuo em eventos de transição."""

    _UNSET = object()

    def __init__(self) -> None:
        self._last: object = self._UNSET

    def update(self, phase: GameflowPhase) -> bool:
        if self._last is phase:
            return False
        self._last = phase
        return True

    def reset(self) -> None:
        self._last = self._UNSET
