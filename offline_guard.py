"""Enforce the offline claim.

Importing this module neuters the network so nothing can phone home, while
still permitting **loopback** (127.0.0.1 / ::1 / localhost) and local Unix
sockets.  The loopback exception exists because the desktop app's webview
allocates a free port by binding a socket to localhost at startup — a purely
local operation — yet the guarantee that matters is unchanged: **no connection
to any non-loopback address, and no DNS lookup for any remote host, can
succeed.**  A dependency that tries to reach the internet still crashes loudly.

We install the block eagerly on import, before any real work happens, so the
guarantee is structural rather than a promise in a README.
"""

import socket

# Capture the genuine primitives before we shadow the module-level names.
_real_socket = socket.socket
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


class OfflineViolation(RuntimeError):
    """Raised when code attempts non-loopback network access."""


def _is_loopback_host(host):
    """True for loopback / unspecified / local hosts — anything that cannot
    leave this machine.  Fails closed: unknown or remote hosts return False."""
    if host is None:
        return True
    h = host.decode() if isinstance(host, (bytes, bytearray)) else str(host)
    h = h.strip("[]").lower()  # strip IPv6 brackets
    if h in ("", "localhost", "127.0.0.1", "::1", "0.0.0.0", "::"):
        return True
    return h.startswith("127.")  # whole 127.0.0.0/8 loopback range


def _check_address(address):
    """Allow local addresses (loopback tuples, Unix-socket paths); block the
    rest with a clear error."""
    # Unix domain socket address is a str/bytes path -> local, allow.
    if isinstance(address, (str, bytes, bytearray)):
        return
    host = address[0] if isinstance(address, (tuple, list)) and address else None
    if not _is_loopback_host(host):
        raise OfflineViolation(
            "Network access is disabled: this tool is offline-only. "
            "Blocked a connection to %r — a dependency tried to phone home."
            % (host,)
        )


class _GuardedSocket(_real_socket):
    """A real socket whose outbound connect() is confined to loopback.

    Binding/listening locally (what the app's webview needs) is untouched;
    only *reaching out* to a non-loopback address is refused.
    """

    def connect(self, address):
        _check_address(address)
        return super().connect(address)

    def connect_ex(self, address):
        _check_address(address)
        return super().connect_ex(address)


def _guarded_create_connection(address, *args, **kwargs):
    _check_address(address)
    return _real_create_connection(address, *args, **kwargs)


def _guarded_getaddrinfo(host, *args, **kwargs):
    # Resolving a remote hostname is itself a step toward phoning home; only
    # loopback / local names may be resolved.
    if not _is_loopback_host(host):
        raise OfflineViolation(
            "Network access is disabled: this tool is offline-only. "
            "Blocked a DNS lookup for %r — a dependency tried to phone home."
            % (host,)
        )
    return _real_getaddrinfo(host, *args, **kwargs)


def install():
    """Confine networking to loopback.

    Some stdlib modules (``ssl``, ``http.client``) subclass ``socket.socket``
    at import time, so we pre-import them first (this opens no connection),
    then swap in the guarded primitives.  After this, any actual attempt to
    reach a non-loopback address — via a new socket's connect,
    create_connection, or a remote DNS lookup — raises ``OfflineViolation``.
    """
    try:  # best-effort: pre-load the modules that inherit from socket
        import ssl  # noqa: F401
        import http.client  # noqa: F401
    except Exception:
        pass

    socket.socket = _GuardedSocket             # type: ignore[assignment]
    socket.create_connection = _guarded_create_connection  # type: ignore[assignment]
    socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]


# Install on import — there is no "later", the whole point is "before any work".
install()
