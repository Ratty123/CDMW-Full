"""Off-thread preparation and command workers for the managed Rust Mesh Editor."""

from __future__ import annotations

import os
import shutil
import stat
import threading
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, _canonical_json_bytes


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
    progress = Signal(int, str)
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
        hair_start_mode: str = "",
        item_set_contexts: tuple = (),
        edit_item_set: bool = False,
        before_prepare=None,
        discarded: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        #: Set when the user chose Discard while this open ran (section 8.9): an
        #: open that then fails or stops ends the draft's recovery point too.
        self.discarded = discarded
        #: Runs first on this thread: binding the resolved preview materials to the
        #: controller, which used to take tens of milliseconds on the UI thread.
        self.before_prepare = before_prepare
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
        self.hair_start_mode = hair_start_mode
        self.item_set_contexts = tuple(item_set_contexts)
        self.edit_item_set = bool(edit_item_set)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _user_discarded(self) -> bool:
        return bool(self.discarded is not None and self.discarded.is_set())

    def _discard_draft_recovery(self) -> None:
        """Discard before any session existed: the draft's recovery point goes, as
        the session's own close would end it."""

        from cdmw.services import mesh_history_journal as journal

        try:
            draft = self.expected_authoritative_service._session(self.expected_session_id)
            project_path = getattr(draft, "mesh_layer_project_path", None)
        except (AttributeError, KeyError, RuntimeError):
            return
        if project_path is None:
            return
        project_root = Path(project_path).parent
        with journal.project_lock(project_root):
            journal.clear_editor_recovery(project_root)

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

    def _report_progress(self, message: str) -> None:
        if not self._controller_context_is_current():
            self._stop_event.set()
        if not self._stop_event.is_set():
            self.progress.emit(self.request_id, message)

    @Slot()
    def run(self) -> None:
        session: RustMeshAuthoringSession | None = None
        transferred = False
        try:
            if self._stop_event.is_set() or not self._controller_context_is_current():
                self._stop_event.set()
                return
            before_prepare_ms = 0.0
            if self.before_prepare is not None:
                import time as _time

                before_started = _time.perf_counter()
                try:
                    self.before_prepare()
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    raise RuntimeError(f"Mesh Editor could not bind the resolved preview textures: {exc}") from exc
                if self._stop_event.is_set() or not self._controller_context_is_current():
                    self._stop_event.set()
                    return
                before_prepare_ms = round((_time.perf_counter() - before_started) * 1000.0, 1)
            session = RustMeshAuthoringSession.create(
                self.authoritative_controller,
                self.session_root,
                process_generation=self.process_generation,
                theme=self.theme,
                stop_event=self._stop_event,
                progress=self._report_progress,
                **({"hair_start_mode": self.hair_start_mode} if self.hair_start_mode else {}),
                **({"item_set_contexts": self.item_set_contexts} if self.item_set_contexts else {}),
                **({"edit_item_set": True} if self.edit_item_set else {}),
                # The editor shows first and receives its morph data later (P4 V3).
                **({"defer_morph_state": True} if getattr(self, "defer_morph_state", True) else {}),
            )
            stages = getattr(session, "open_stage_ms", None)
            if isinstance(stages, dict) and before_prepare_ms:
                stages["material_prime_ms"] = before_prepare_ms  # resolved on this worker since V1
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
                    # A failed open keeps the recovery point, unless the user chose Discard.
                    session.close(discard=self._user_discarded())
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
                    # An aborted open keeps the recovery point, unless the user chose Discard.
                    session.close(discard=self._user_discarded())
                except Exception:
                    pass
            elif not transferred and self._user_discarded():
                try:
                    self._discard_draft_recovery()
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
        *,
        preparation_error: str = "",
    ) -> None:
        super().__init__()
        self.worker_request_id = int(worker_request_id)
        self.session = session
        # QObject.event() must remain callable.  A Python instance attribute
        # named ``event`` masks that Qt virtual and makes moveToThread() fail
        # before the first real protocol transaction can start.
        self.protocol_event = dict(event)
        self._preparation_error = str(preparation_error)
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
            if self._preparation_error:
                # Picker rejection needs the same authoritative recovery state
                # as worker failures, prepared here rather than on the UI thread.
                raise ValueError(self._preparation_error)
            finish_accepted = False
            if event_name == "vertex_inspect":
                payload = self.session.vertex_inspect(self.protocol_event, stop_event=self._stop_event)
                result_name = "vertex_inspect_result"
            elif event_name == "transaction_request":
                payload = self.session.apply_candidate(self.protocol_event, stop_event=self._stop_event)
                result_name = "transaction_result"
            elif event_name == "command_request":
                if self.protocol_event.get("command") in {"refit_choose_archive", "hair_begin"}:
                    from cdmw.workers.mesh_archive_refit_worker import prepare_archive_refit_source, prepare_hair_reference_source
                    prepare_source = prepare_hair_reference_source if self.protocol_event.get("command") == "hair_begin" else prepare_archive_refit_source
                    self.protocol_event["arguments"] = prepare_source(
                        dict(self.protocol_event.get("arguments") or {}), self._stop_event,
                    )
                    args = self.protocol_event["arguments"]
                    if self.protocol_event.get("command") == "hair_begin" and args.get("_body_archive_entry") is not None:
                        body = prepare_hair_reference_source({"_archive_entry": args["_body_archive_entry"],
                            "_archive_dependencies": args["_body_archive_dependencies"],
                            "_hair_authored_descriptors": args.get("_hair_authored_descriptors"),
                            "_hair_context_identity": args.get("_hair_context_identity")}, self._stop_event)
                        args["_body_snapshot"] = body["_archive_snapshot"]
                        args["_body_neutral_appearance"] = body["_archive_neutral_appearance"]
                        args["_body_skeleton"] = body.get("_archive_skeleton")
                        args["_body_preview_lease"] = body["_archive_preview_lease"]
                    if self.protocol_event.get("command") == "hair_begin":
                        args["_prepared_head_details"] = []
                        for entry, scale in args.get("_head_details", ()):
                            detail = prepare_hair_reference_source({"_archive_entry": entry,
                                "_archive_dependencies": args["_archive_dependencies"],
                                "_hair_authored_descriptors": args.get("_hair_authored_descriptors"),
                                "_hair_context_identity": args.get("_hair_context_identity")}, self._stop_event)
                            detail["_scale"] = scale
                            args["_prepared_head_details"].append(detail)
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
                "payload": self._prepare_control_payload(payload),
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
                if not self.session.closed and event_name != "vertex_inspect":
                    try:
                        include_document = not (
                            event_name == "command_request"
                            and str(self.protocol_event.get("command", "") or "").strip().lower()
                            == "refit_diagnostics"
                        )
                        recovery = {
                            "state": self.session.state_payload(include_document=include_document)
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
                try:
                    recovery = self._prepare_control_payload(recovery)
                except (OSError, RuntimeError, TypeError, ValueError):
                    recovery = {}
                self.error.emit(
                    self.worker_request_id,
                    int(self.protocol_event.get("request_id", 0) or 0),
                    event_name or "error",
                    str(exc),
                    recovery,
                )
        finally:
            if self.protocol_event.get("command") == "hair_begin":
                for detail in dict(self.protocol_event.get("arguments") or {}).get("_prepared_head_details", ()):
                    lease = detail.get("_archive_preview_lease")
                    if lease is not None and lease.lease is not None:
                        lease.lease.release()
                        lease.lease = None
                for key in ("_archive_preview_lease", "_body_preview_lease"):
                    lease = dict(self.protocol_event.get("arguments") or {}).get(key)
                    if lease is not None and lease.lease is not None:
                        lease.lease.release()
                        lease.lease = None
            self.finished.emit()

    def _prepare_control_payload(self, payload: dict[str, object]) -> dict[str, object]:
        # Inspections are independently cancellable and may overlap a command.
        # Keep their bounded pages inline rather than sharing the command file.
        if self.protocol_event.get("event") == "vertex_inspect":
            return payload
        # Reserve space for the envelope beneath Rust's 256 KiB control-line cap.
        if len(_canonical_json_bytes(payload)) <= 192 * 1024:
            return payload
        return self.session.stage_control_payload(payload)

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
                # A dispose is not a Discard: only a Discard the user chose (marked on
                # the session) ends the recovery point (section 8.9).
                self.session.close()
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
