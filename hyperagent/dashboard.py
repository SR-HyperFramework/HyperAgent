"""Serve the web UI from inside a running ``hyperagent analyze``.

The CLI starts this next to the console so a run can be watched in a browser
while it happens: the Flask app from ``webui/`` gets the run console as its
live feed, which lets ``/live/<sha256>`` show the agent trace alongside what
the report directory already holds. The server runs on a daemon thread, binds
to loopback only (the pages carry sample-derived text), and stops with the
process.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PORT = 5000
#: How many consecutive ports to try when the requested one is taken, e.g.
#: by a standalone ``python webui/app.py`` already on 5000.
PORT_ATTEMPTS = 10
_HOST = "127.0.0.1"
_REPO_ROOT = Path(__file__).resolve().parents[1]


class DashboardUnavailable(RuntimeError):
    """The dashboard could not be started; the run continues without it."""


@dataclass
class LiveDashboard:
    url: str
    _server: Any
    _thread: threading.Thread

    def close(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # pragma: no cover - shutdown is best-effort at exit
            logger.debug("Dashboard shutdown failed", exc_info=True)
        self._thread.join(timeout=2)


def _port_is_free(port: int) -> bool:
    """Probe without SO_REUSEADDR: on Windows werkzeug's own reuse flag would
    otherwise let it share a port another server is already listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((_HOST, port))
        except OSError:
            return False
    return True


def _create_app(reports_root: Path, live_feed: Any) -> Any:
    try:
        from webui.app import create_app
    except ImportError:
        # `webui` is a sibling of the package, not part of it, so it is only
        # importable from a checkout. Running from one is the supported setup.
        if (_REPO_ROOT / "webui" / "app.py").is_file() and str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        try:
            from webui.app import create_app
        except ImportError as exc:
            raise DashboardUnavailable(f"web UI not importable ({exc})") from exc
    return create_app(reports_root, live_feed=live_feed)


def start_dashboard(
    *,
    reports_root: Path,
    live_feed: Any,
    port: int = DEFAULT_PORT,
    attempts: int = PORT_ATTEMPTS,
) -> LiveDashboard:
    """Start the web UI on the first free port from *port* upward."""
    try:
        from werkzeug.serving import make_server
    except ImportError as exc:  # Flask (and so werkzeug) is a declared dependency
        raise DashboardUnavailable(f"werkzeug not installed ({exc})") from exc

    app = _create_app(Path(reports_root), live_feed)
    last_error: BaseException | None = None
    for candidate in range(port, port + max(1, attempts)):
        if not _port_is_free(candidate):
            continue
        try:
            server = make_server(_HOST, candidate, app, threaded=True)
        except (OSError, SystemExit) as exc:
            # werkzeug reports a failed bind with sys.exit(1), not an
            # exception; that must not end the analysis run.
            last_error = exc
            continue
        thread = threading.Thread(
            target=server.serve_forever, name="hyperagent-dashboard", daemon=True
        )
        thread.start()
        url = f"http://{_HOST}:{server.server_port}"
        logger.debug("Live dashboard serving %s on %s", reports_root, url)
        return LiveDashboard(url=url, _server=server, _thread=thread)
    detail = f" ({last_error})" if last_error is not None else ""
    raise DashboardUnavailable(f"no free port in {port}-{port + attempts - 1}{detail}")
