"""Enforce the offline claim.

Importing this module *replaces* the network primitives in the standard
``socket`` module with functions that raise.  Anything that tries to open a
TCP connection or resolve a hostname after this point crashes loudly instead
of silently phoning home.  We install the block eagerly, before any real work
happens, so the guarantee is structural rather than a promise in a README.
"""

import socket


class OfflineViolation(RuntimeError):
    """Raised when code attempts network access in this offline-only tool."""


def _blocked(*_args, **_kwargs):
    raise OfflineViolation(
        "Network access is disabled: this tool is offline-only. "
        "If you see this, a dependency tried to phone home."
    )


def install():
    """Patch socket so any outbound connection attempt raises.

    Some stdlib modules (``ssl``, ``http.client``) subclass ``socket.socket``
    at import time.  We import them first so that subclassing still sees a real
    class; importing them opens no connection.  After that we replace the
    connection primitives, so any *actual* attempt to reach the network — new
    socket, connect, or DNS lookup — raises.
    """
    try:  # best-effort: pre-load the modules that inherit from socket
        import ssl  # noqa: F401
        import http.client  # noqa: F401
    except Exception:
        pass

    socket.socket = _blocked            # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked        # type: ignore[assignment]


# Install on import — there is no "later", the whole point is "before any work".
install()
