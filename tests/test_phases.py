from lolqueue.core.phases import END_PHASES, GameflowPhase, PhaseTracker


def test_parses_known_phase():
    assert GameflowPhase.parse("ReadyCheck") is GameflowPhase.READY_CHECK


def test_unknown_phase_does_not_explode():
    assert GameflowPhase.parse("SomethingRiotAddedLater") is GameflowPhase.UNKNOWN
    assert GameflowPhase.parse(None) is GameflowPhase.UNKNOWN


def test_end_phases_cover_the_post_game_flow():
    assert GameflowPhase.END_OF_GAME in END_PHASES
    assert GameflowPhase.PRE_END_OF_GAME in END_PHASES
    assert GameflowPhase.WAITING_FOR_STATS in END_PHASES
    assert GameflowPhase.LOBBY not in END_PHASES


def test_tracker_reports_first_observation_as_a_change():
    tracker = PhaseTracker()
    assert tracker.update(GameflowPhase.LOBBY) is True


def test_tracker_stays_quiet_while_phase_repeats():
    tracker = PhaseTracker()
    tracker.update(GameflowPhase.LOBBY)
    assert tracker.update(GameflowPhase.LOBBY) is False
    assert tracker.update(GameflowPhase.LOBBY) is False


def test_tracker_reports_real_transitions():
    tracker = PhaseTracker()
    tracker.update(GameflowPhase.LOBBY)
    assert tracker.update(GameflowPhase.READY_CHECK) is True


def test_reset_makes_the_next_observation_a_change_again():
    tracker = PhaseTracker()
    tracker.update(GameflowPhase.LOBBY)
    tracker.reset()
    assert tracker.update(GameflowPhase.LOBBY) is True
