"""Desktop must reserve a loopback-only port without disturbing web 8765."""
import socket
from desktop.backend_launcher import READY_PREFIX, reserve_loopback


def test_desktop_listener_is_loopback():
    listener, port = reserve_loopback()
    try:
        assert listener.getsockname()[0] == "127.0.0.1"
        assert 0 < port < 65536
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    finally:
        listener.close()


def test_two_instances_cannot_claim_the_same_bound_port():
    a, first = reserve_loopback()
    b, second = reserve_loopback()
    try:
        assert first != second
        assert READY_PREFIX == "CENTRAL_DESKTOP_READY="
    finally:
        a.close()
        b.close()
