"""Running a translation pass: batches out, checked lines back, cancellable throughout.

A pass over the whole English table is 187,521 lines and thousands of requests, so this
layer is about what happens when that goes wrong halfway. Three rules follow from it:

**Partial work is kept.** Each batch is applied to the catalogue as it lands, not at the
end, so cancelling after twenty minutes leaves twenty minutes of translation in the table
rather than nothing.

**A rate limit is not a failure.** 429 and 5xx are retried with backoff, honouring
`Retry-After` when the provider sends one; the sleep is sliced so Cancel still answers.

**A line whose markup came back wrong is not applied.** It is reported with the tokens
that changed, and left as the game shipped it. Silently writing a broken `{Key:...}` into
187,521 lines is the one outcome no one could review.

The transport is injectable so the tests can run a whole pass, retries and all, without
a network or a key.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .ai_provider import ProviderConfig
from .ai_translate import (
    HttpRequest,
    Line,
    ProviderError,
    TranslationBrief,
    build_batches,
    build_request,
    describe_error,
    extract_text,
    parse_translations,
    token_mismatch,
)

_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = (2.0, 6.0, 15.0)
#: Providers answer a bad key or a wrong model instantly; only these are worth waiting on.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})

#: `(request, timeout) -> (status, body)`.
Transport = Callable[[HttpRequest, float], Tuple[int, bytes]]


def http_transport(request: HttpRequest, timeout: float) -> Tuple[int, bytes]:
    """The real one. Reads the body on an error status too -- that is where the reason is."""

    prepared = Request(request.url, data=request.body, headers=dict(request.headers), method="POST")
    try:
        with urlopen(prepared, timeout=timeout) as response:
            return int(response.status or 0), response.read()
    except HTTPError as error:
        try:
            body = error.read()
        except Exception:  # noqa: BLE001
            body = b""
        return int(error.code), body
    except URLError as error:
        raise ProviderError(f"could not reach the provider: {error.reason}", retryable=True) from error
    except TimeoutError as error:
        raise ProviderError("the provider timed out", retryable=True) from error


# ----------------------------------------------------------------- one request


def _retry_after(body: bytes, default: float) -> float:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return default
    if isinstance(payload, dict):
        for key in ("retry_after", "retryAfter"):
            try:
                return float(payload[key])
            except (KeyError, TypeError, ValueError):
                continue
    return default


def send_once(
    config: ProviderConfig, system: str, user: str, *, transport: Transport
) -> str:
    """One round trip. Raises `ProviderError` with `retryable` set for the caller."""

    request = build_request(config, system, user)
    status, body = transport(request, float(config.timeout))
    if status != 200:
        message = describe_error(status, body)
        retryable = status in _RETRYABLE_STATUS
        raise ProviderError(
            message, retryable=retryable, retry_after=_retry_after(body, 0.0) if retryable else 0.0
        )
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError as error:
        raise ProviderError("the provider did not return JSON") from error
    if not isinstance(payload, dict):
        raise ProviderError("the provider returned an unexpected reply")
    return extract_text(config.api, payload)


def _sleep(seconds: float, should_stop: Callable[[], bool]) -> None:
    """Wait in slices so Cancel still answers during a rate-limit backoff."""

    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if should_stop():
            return
        time.sleep(min(0.25, deadline - time.monotonic()))


def send_with_retry(
    config: ProviderConfig,
    system: str,
    user: str,
    *,
    transport: Transport,
    should_stop: Callable[[], bool],
) -> str:
    last = ""
    for attempt in range(_MAX_ATTEMPTS):
        if should_stop():
            raise ProviderError("cancelled")
        try:
            return send_once(config, system, user, transport=transport)
        except ProviderError as error:
            last = str(error)
            if not error.retryable or attempt == _MAX_ATTEMPTS - 1:
                raise
            wait_for = error.retry_after or _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
            _sleep(wait_for, should_stop)
    raise ProviderError(last or "the request failed")


# --------------------------------------------------------------------- results


@dataclass(frozen=True)
class BatchResult:
    """What came back for one request, already checked against the source."""

    number: int
    lines: int
    accepted: Mapping[int, str] = field(default_factory=dict)
    #: `(line index, why)` -- markup that did not survive, or a line the model dropped.
    rejected: Tuple[Tuple[int, str], ...] = ()
    error: str = ""


@dataclass
class JobSummary:
    batches: int = 0
    lines: int = 0
    translated: int = 0
    rejected: int = 0
    failed_batches: int = 0
    cancelled: bool = False
    errors: Tuple[str, ...] = ()

    def describe(self) -> str:
        parts = [f"{self.translated:,} line(s) translated"]
        if self.rejected:
            parts.append(f"{self.rejected:,} left alone (markup changed or line dropped)")
        if self.failed_batches:
            parts.append(f"{self.failed_batches} request(s) failed")
        if self.cancelled:
            parts.append("stopped early")
        return "; ".join(parts) + "."


def check_batch(
    number: int,
    batch: Sequence[Line],
    replies: Mapping[int, str],
    *,
    skip_on_mismatch: bool,
) -> BatchResult:
    """Accept only what came back intact; say why for everything else."""

    accepted: Dict[int, str] = {}
    rejected: List[Tuple[int, str]] = []
    for line in batch:
        reply = replies.get(line.index)
        if reply is None:
            rejected.append((line.index, "the model did not return this line"))
            continue
        text = str(reply)
        if text == line.text:
            # Unchanged is a legitimate answer for a numeric or markup-only line, and
            # recording it as an edit would put a no-op row in the export.
            continue
        changed = token_mismatch(line.text, text)
        if changed and skip_on_mismatch:
            rejected.append((line.index, "markup changed: " + ", ".join(changed)))
            continue
        accepted[line.index] = text
    return BatchResult(number=number, lines=len(batch), accepted=accepted, rejected=tuple(rejected))


# ------------------------------------------------------------------- the pass


def run_job(
    *,
    config: ProviderConfig,
    brief: TranslationBrief,
    lines: Sequence[Line],
    transport: Optional[Transport] = None,
    skip_on_mismatch: bool = True,
    on_result: Optional[Callable[[BatchResult], None]] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> JobSummary:
    """Translate every line, applying each batch through `on_result` as it lands."""

    send = transport or http_transport
    stop = should_stop or (lambda: False)
    batches = build_batches(lines, batch_size=config.batch_size)
    summary = JobSummary(batches=len(batches), lines=len(lines))
    errors: List[str] = []
    system = brief.system_prompt()

    def _one(number: int, batch: Tuple[Line, ...]) -> BatchResult:
        try:
            text = send_with_retry(
                config, system, brief.user_prompt(batch), transport=send, should_stop=stop
            )
            if not text.strip():
                # Usually the reply hit the token ceiling. Reporting it as a failed
                # request names the cause; reporting it as "the model dropped every
                # line" would send the reader looking at the prompt instead.
                raise ProviderError(
                    "the provider returned no text -- try a smaller batch or a higher "
                    "max reply tokens"
                )
            replies = parse_translations(text)
        except ProviderError as error:
            return BatchResult(number=number, lines=len(batch), error=str(error))
        except Exception as error:  # noqa: BLE001 - one bad batch must not end the pass
            return BatchResult(number=number, lines=len(batch), error=str(error))
        return check_batch(number, batch, replies, skip_on_mismatch=skip_on_mismatch)

    workers = max(1, min(int(config.parallel), 16))
    done_count = 0
    pending: Dict[Future, int] = {}
    queue = iter(list(enumerate(batches, start=1)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        def _fill() -> None:
            while len(pending) < workers and not stop():
                try:
                    number, batch = next(queue)
                except StopIteration:
                    return
                pending[pool.submit(_one, number, batch)] = number

        _fill()
        while pending:
            finished, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future, None)
                result = future.result()
                done_count += 1
                if result.error:
                    summary.failed_batches += 1
                    if result.error not in errors and len(errors) < 8:
                        errors.append(result.error)
                summary.translated += len(result.accepted)
                summary.rejected += len(result.rejected)
                if on_result is not None:
                    on_result(result)
                if on_progress is not None:
                    on_progress(done_count, len(batches))
            # `_fill` stops queueing once Cancel is pressed, but the loop keeps draining:
            # a request already in flight has been paid for, so its lines are applied.
            _fill()

    summary.cancelled = bool(stop()) and done_count < len(batches)
    summary.errors = tuple(errors)
    return summary


__all__ = [
    "BatchResult",
    "JobSummary",
    "Transport",
    "check_batch",
    "http_transport",
    "run_job",
    "send_once",
    "send_with_retry",
]
