"""Off-thread preparation and command workers for the managed Rust Mesh Editor."""

from __future__ import annotations

import os
import shutil
import stat
import threading
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession


def _path_is_reparse_point(path: Path) -> bool:
    attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    return bool(
        attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    )


def _remove_owned_session_root(
    session_root: Path,
    owned_root: Path,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    """Remove only the allocated directory entry, never a redirected target."""

    owned = Path(os.path.abspath(os.fspath(owned_root))).resolve(strict=True)
    candidate = Path(os.path.abspath(os.fspath(session_root)))
    if candidate.parent != owned or not candidate.name.startswith("session-"):
        raise RuntimeError("Refusing to clean a Mesh directory not owned by CDMW")
    if not os.path.lexists(candidate):
        return
    if expected_identity is None:
        raise RuntimeError("Refusing to clean a Mesh directory without its identity")
    quarantine = owned / f".rust-mesh-dispose-{uuid4().hex}"
    os.replace(candidate, quarantine)
    try:
        if quarantine.is_symlink() or _path_is_reparse_point(quarantine):
            if quarantine.is_symlink():
                quarantine.unlink()
            else:
                os.rmdir(quarantine)
            return
        quarantined_stat = quarantine.stat()
        quarantined_identity = (
            int(quarantined_stat.st_dev),
            int(quarantined_stat.st_ino),
        )
        if quarantined_identity != tuple(expected_identity):
            if not os.path.lexists(candidate):
                os.replace(quarantine, candidate)
            raise RuntimeError("Refusing to clean a replaced Mesh session directory")
        shutil.rmtree(quarantine)
    except Exception:
        if os.path.lexists(quarantine) and not os.path.lexists(candidate):
            os.replace(quarantine, candidate)
        raise


class MeshRustSessionPrepareWorker(QObject):
    prepared = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        authoritative_controller: object,
        session_root: Path | str,
        *,
        process_generation: int,
        theme: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.authoritative_controller = authoritative_controller
        self.expected_controller_identity = id(authoritative_controller)
        self.expected_authoritative_service = getattr(
            authoritative_controller,
            "mesh_service",
            None,
        )
        self.expected_session_id = str(
            getattr(authoritative_controller, "active_session_id", "") or ""
        )
        self.session_root = Path(session_root)
        self.process_generation = int(process_generation)
        self.theme = dict(theme or {})
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _controller_context_is_current(self) -> bool:
        return bool(
            id(self.authoritative_controller) == self.expected_controller_identity
            and getattr(self.authoritative_controller, "mesh_service", None)
            is self.expected_authoritative_service
            and self.expected_authoritative_service is not None
            and self.expected_session_id
            and str(
                getattr(self.authoritative_controller, "active_session_id", "") or ""
            )
            == self.expected_session_id
        )

    @Slot()
    def run(self) -> None:
        session: RustMeshAuthoringSession | None = None
        transferred = False
        try:
            if self._stop_event.is_set() or not self._controller_context_is_current():
                self._stop_event.set()
                return
            session = RustMeshAuthoringSession.create(
                self.authoritative_controller,
                self.session_root,
                process_generation=self.process_generation,
                theme=self.theme,
                stop_event=self._stop_event,
            )
            if (
                self._stop_event.is_set()
                or not self._controller_context_is_current()
                or str(getattr(session, "authoritative_session_id", "") or "")
                != self.expected_session_id
                or getattr(session, "authoritative_service", None)
                is not self.expected_authoritative_service
                or int(getattr(session, "process_generation", 0) or 0)
                != self.process_generation
            ):
                self._stop_event.set()
                return
            self.prepared.emit(self.request_id, session)
            transferred = True
            session = None
        except Exception as exc:  # pragma: no cover - exact text is surfaced by owning UI tests
            if session is not None:
                try:
                    session.cancel()
                    _remove_owned_session_root(
                        self.session_root,
                        self.session_root.parent,
                        expected_identity=session.root_identity,
                    )
                except Exception as cleanup_exc:
                    exc = RuntimeError(f"{exc} (session cleanup pending: {cleanup_exc})")
            if not self._stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            if session is not None:
                try:
                    session.cancel()
                except Exception:
                    pass
            if not transferred and self._stop_event.is_set() and session is not None:
                try:
                    _remove_owned_session_root(
                        self.session_root,
                        self.session_root.parent,
                        expected_identity=session.root_identity,
                    )
                except Exception:
                    pass
            self.finished.emit()


class MeshRustProtocolWorker(QObject):
    completed = Signal(int, int, dict, bool)
    error = Signal(int, int, str, str, dict)
    finished = Signal()

    def __init__(
        self,
        worker_request_id: int,
        session: RustMeshAuthoringSession,
        event: dict[str, object],
    ) -> None:
        super().__init__()
        self.worker_request_id = int(worker_request_id)
        self.session = session
        # QObject.event() must remain callable.  A Python instance attribute
        # named ``event`` masks that Qt virtual and makes moveToThread() fail
        # before the first real protocol transaction can start.
        self.protocol_event = dict(event)
        self._stop_event = threading.Event()

    def stop(self) -> bool:
        self._stop_event.set()
        if str(self.protocol_event.get("event", "") or "").strip().lower() == "finish_request":
            return bool(self.session.request_cancel())
        return True

    @Slot()
    def run(self) -> None:
        try:
            event_name = str(self.protocol_event.get("event", "") or "").strip().lower()
            client_request_id = int(self.protocol_event.get("request_id", 0) or 0)
            if self._stop_event.is_set():
                return
            finish_accepted = False
            if event_name == "transaction_request":
                payload = self.session.apply_candidate(self.protocol_event)
                result_name = "transaction_result"
            elif event_name == "command_request":
                payload = self.session.run_command(
                    self.protocol_event,
                    stop_event=self._stop_event,
                )
                result_name = "command_result"
            elif event_name == "finish_request":
                payload = self.session.finish(
                    self.protocol_event,
                    stop_event=self._stop_event,
                )
                result_name = "finish_result"
                finish_accepted = True
            elif event_name == "cancel":
                self.session.cancel()
                payload = {"status": "cancelled"}
                result_name = "cancel"
            else:
                raise ValueError(f"Unsupported Mesh protocol event: {event_name or '(empty)'}")
            if self._stop_event.is_set() and not finish_accepted:
                return
            response = {
                "event": result_name,
                "protocol": str(self.protocol_event.get("protocol", "") or ""),
                "session_id": str(self.protocol_event.get("session_id", "") or ""),
                "request_id": client_request_id,
                "base_revision": self._response_revision(),
                "process_generation": int(self.protocol_event.get("process_generation", 0) or 0),
                "ok": True,
                "payload": payload,
            }
            self.completed.emit(
                self.worker_request_id,
                client_request_id,
                response,
                finish_accepted,
            )
        except Exception as exc:  # pragma: no cover - owning tests assert surfaced response
            event_name = str(self.protocol_event.get("event", "") or "").strip().lower()
            if not self._stop_event.is_set() or event_name == "finish_request":
                recovery: dict[str, object] = {}
                if not self.session.closed:
                    try:
                        recovery = {
                            "state": self.session.state_payload(include_document=True)
                        }
                    except (KeyError, RuntimeError, TypeError, ValueError):
                        try:
                            request_revision = int(
                                self.protocol_event.get("base_revision", -1)
                            )
                            current_revision = int(
                                self.session.shadow_service.session_view(
                                    self.session.shadow_session_id
                                ).revision
                            )
                            if current_revision == request_revision:
                                recovery = {
                                    "state": self.session.state_payload(
                                        include_document=False
                                    )
                                }
                        except (KeyError, RuntimeError, TypeError, ValueError):
                            recovery = {}
                self.error.emit(
                    self.worker_request_id,
                    int(self.protocol_event.get("request_id", 0) or 0),
                    event_name or "error",
                    str(exc),
                    recovery,
                )
        finally:
            self.finished.emit()

    def _response_revision(self) -> int:
        if self.session.closed:
            return int(self.protocol_event.get("base_revision", 0) or 0)
        return int(
            self.session.shadow_service.session_view(self.session.shadow_session_id).revision
        )


class MeshRustSessionDisposeWorker(QObject):
    completed = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        session: RustMeshAuthoringSession | None,
        session_root: Path | str,
        owned_root: Path | str,
    ) -> None:
        super().__init__()
        self.session = session
        self.session_root = Path(session_root)
        self.owned_root = Path(owned_root)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    @Slot()
    def run(self) -> None:
        failure: Exception | None = None
        expected_identity: tuple[int, int] | None = None
        try:
            if self.session is not None:
                expected_identity = self.session.root_identity
            if self.session is not None and not self.session.closed:
                self.session.cancel()
        except Exception as exc:
            # Cancelling the shadow service is independent from releasing its
            # owned package.  A failed or stopped cancel must never strand the
            # identity-pinned session directory during shell shutdown.
            failure = exc
        try:
            _remove_owned_session_root(
                self.session_root,
                self.owned_root,
                expected_identity=expected_identity,
            )
        except Exception as cleanup_exc:
            if failure is None:
                failure = cleanup_exc
            else:
                failure = RuntimeError(
                    f"{failure} (session cleanup pending: {cleanup_exc})"
                )
        try:
            if failure is not None:
                raise failure
            if not self._stop_event.is_set():
                self.completed.emit(str(self.session_root))
        except Exception as exc:  # pragma: no cover - exact text is surfaced by owning UI tests
            if not self._stop_event.is_set():
                self.error.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = [
    "MeshRustProtocolWorker",
    "MeshRustSessionDisposeWorker",
    "MeshRustSessionPrepareWorker",
]
