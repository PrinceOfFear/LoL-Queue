from lolqueue.core.watcher import POLL_INTERVAL, RECONNECT_INTERVAL, ConnectionState


def test_starts_disconnected():
    state = ConnectionState()
    assert state.connected is False
    assert state.interval == RECONNECT_INTERVAL


def test_connecting_reports_a_change_once():
    state = ConnectionState()
    assert state.set_connected(True) is True
    assert state.set_connected(True) is False


def test_connected_polls_faster():
    state = ConnectionState()
    state.set_connected(True)
    assert state.interval == POLL_INTERVAL


def test_disconnecting_reports_a_change_and_slows_down():
    state = ConnectionState()
    state.set_connected(True)
    assert state.set_connected(False) is True
    assert state.interval == RECONNECT_INTERVAL
