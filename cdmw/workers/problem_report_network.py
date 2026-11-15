"""Problem report requests through the standard library, off the UI thread.

The report dialog used Qt Network for three requests (start the browser check,
poll it, upload the reviewed report). This module sends the same requests with
``urllib`` on a worker thread so the release does not need Qt Network's binding
or its TLS plugins for them.

What is kept from the Qt version, deliberately:
- redirects are never followed, so the access key and the evidence never reach
  a redirect target; a 3xx answer comes back as that status;
- the content type is ``application/json`` and the ticket, when there is one,
  goes in ``Authorization: Bearer``;
- an HTTP error still returns its status, body and ``Retry-After``, because the
  service explains refusals in the body;
- ``abort()`` reports the request as finished at once with status 0, as
  ``QNetworkReply.abort()`` does, and whatever the thread receives later is
  dropped.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot

REPORT_REQUEST_TIMEOUT_SECONDS = 45.0
REPORT_USER_AGENT = "CrimsonDesertModWorkbench/ProblemReport"
_MAX_RESPONSE_BYTES = 1 << 20

_active_requests: set["ReportNetworkRequest"] = set()


@dataclass(frozen=True)
class ReportHttpResult:
    """What the dialog reads from a finished request.

    ``error`` is empty when an HTTP answer arrived (any status); otherwise it
    names why none did (no connection, timeout, aborted) and ``status`` is 0.
    """

    status: int = 0
    body: bytes = b""
    retry_after: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 300


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib hook
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def send_report_request(
    url: str,
    body: bytes | None = None,
    *,
    ticket: str = "",
    timeout: float = REPORT_REQUEST_TIMEOUT_SECONDS,
) -> ReportHttpResult:
    """Send one request and return its answer; never raises for network faults."""

    headers = {"Content-Type": "application/json", "User-Agent": REPORT_USER_AGENT}
    if ticket:
        headers["Authorization"] = f"Bearer {ticket}"
    request = urllib.request.Request(
        url,
        data=None if body is None else bytes(body),
        headers=headers,
        method="GET" if body is None else "POST",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return ReportHttpResult(
                int(response.status),
                response.read(_MAX_RESPONSE_BYTES),
                str(response.headers.get("Retry-After", "") or ""),
            )
    except urllib.error.HTTPError as error:
        try:
            payload = error.read(_MAX_RESPONSE_BYTES)
        except OSError:
            payload = b""
        finally:
            error.close()
        headers = error.headers
        retry_after = str(headers.get("Retry-After", "") or "") if headers is not None else ""
        return ReportHttpResult(int(error.code), payload, retry_after)
    except (urllib.error.URLError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        return ReportHttpResult(error=str(reason) or type(error).__name__)


class ReportNetworkRequest(QObject):
    """One report request on its own thread; ``finished`` fires once, on the UI thread."""

    finished = Signal(object)

    def __init__(
        self,
        url: str,
        body: bytes | None = None,
        *,
        ticket: str = "",
        timeout: float = REPORT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self._url = url
        self._body = None if body is None else bytes(body)
        self._ticket = ticket
        self._timeout = timeout
        self._lock = threading.Lock()
        self._delivered = False
        self._thread: threading.Thread | None = None
        # The worker emits from its own thread; this queued hop delivers on the
        # thread that owns the object (the UI thread).
        self._result_ready.connect(self._deliver)

    _result_ready = Signal(object)

    def start(self) -> None:
        _active_requests.add(self)
        self._thread = threading.Thread(target=self._run, name="cdmw-problem-report-request", daemon=True)
        self._thread.start()

    def abort(self) -> None:
        if self._claim():
            self.finished.emit(ReportHttpResult(error="aborted"))

    @property
    def is_finished(self) -> bool:
        with self._lock:
            return self._delivered

    def _claim(self) -> bool:
        with self._lock:
            if self._delivered:
                return False
            self._delivered = True
            return True

    def _run(self) -> None:
        result = send_report_request(self._url, self._body, ticket=self._ticket, timeout=self._timeout)
        try:
            self._result_ready.emit(result)
        except RuntimeError:  # the Qt object is already gone at application exit
            _active_requests.discard(self)

    @Slot(object)
    def _deliver(self, result: object) -> None:
        _active_requests.discard(self)
        if self._claim():
            self.finished.emit(result)
