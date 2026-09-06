from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_pac_topology_serializer import _pac_fixture


pytestmark = pytest.mark.visual

_ROOT = Path(__file__).resolve().parents[1]
_HANDSHAKE_TIMEOUT_SECONDS = 12.0
_EXIT_TIMEOUT_SECONDS = 8.0


class _Settings:
    def __init__(self, path: Path) -> None:
        self.path = path

    def fileName(self) -> str:  # noqa: N802 - QSettings-compatible test double
        return str(self.path)


def _release_helper() -> Path:
    if os.name != "nt":
        pytest.skip("the Edit Mesh lifecycle helper is Windows-only")
    candidates = (
        _ROOT / "tools" / "rust_mesh_lab" / "target" / "release" / "cdmw_mesh_lab.exe",
        _ROOT
        / "native"
        / "rust_mesh_editor"
        / "build"
        / "Release"
        / "cdmw_mesh_lab.exe",
    )
    helper = next((candidate for candidate in candidates if candidate.is_file()), None)
    if helper is None:
        pytest.skip("the Release cdmw_mesh_lab.exe helper is unavailable")
    return helper.resolve()


def _bc1_mip_tail_dds() -> bytes:
    """Return a complete 4x4 BC1 texture with physical blocks for all three mips."""

    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = (4).to_bytes(4, "little")
    header[12:16] = (4).to_bytes(4, "little")
    header[16:20] = (8).to_bytes(4, "little")
    header[24:28] = (3).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = b"DXT1"
    header[104:108] = (0x401008).to_bytes(4, "little")
    # BC1 stores one physical 4x4 block even when the logical mip is 2x2 or 1x1.
    return b"DDS " + bytes(header) + (b"\x00" * (8 * 3))


def _authoritative_controller(root: Path, texture: Path) -> tuple[MeshService, object]:
    service = MeshService(settings=_Settings(root / "settings.ini"))
    source = _pac_fixture(skinned=False)
    mesh = parse_pac(source, "synthetic-rust-lifecycle.pac")
    setattr(mesh, "_cdmw_original_data", source)
    setattr(
        mesh,
        "_cdmw_no_op_roundtrip_report",
        {"result": "PASS", "byte_identical": True, "unexpected_differences": 0},
    )
    mesh.submeshes[0].preview_texture_dds_path = str(texture)
    view = service.open_edit_session(
        mesh,
        session_id="authoritative-rust-lifecycle",
        mode="edit",
    )
    return service, SimpleNamespace(mesh_service=service, active_session_id=view.session_id)


def _write_host_message(
    process: subprocess.Popen[str],
    session: RustMeshAuthoringSession,
    event: str,
    *,
    request_id: int,
    extra: dict[str, object] | None = None,
) -> None:
    assert process.stdin is not None
    payload: dict[str, object] = {
        "event": event,
        "protocol": RUST_MESH_EDITOR_PROTOCOL,
        "session_id": session.session_id,
        "request_id": request_id,
        "base_revision": session.shadow_service.session_view(
            session.shadow_session_id
        ).revision,
        "process_generation": session.process_generation,
    }
    payload.update(extra or {})
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _reader(
    stream: object,
    lines: list[str],
    messages: queue.Queue[dict[str, object] | str | None] | None = None,
) -> None:
    try:
        for line in stream:  # type: ignore[union-attr]
            lines.append(line.rstrip("\r\n"))
            if messages is not None:
                try:
                    payload = json.loads(line)
                except ValueError:
                    messages.put(line.rstrip("\r\n"))
                else:
                    messages.put(payload if isinstance(payload, dict) else line.rstrip("\r\n"))
    finally:
        if messages is not None:
            messages.put(None)


def _stop_process(process: subprocess.Popen[str], session: RustMeshAuthoringSession) -> None:
    if process.poll() is not None:
        return
    try:
        _write_host_message(
            process,
            session,
            "cancel",
            request_id=99,
            extra={"reason": "test cleanup"},
        )
        process.wait(timeout=2.0)
        return
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
        pass
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def _run_one_lifecycle(
    helper: Path,
    session: RustMeshAuthoringSession,
) -> tuple[str, ...]:
    environment = os.environ.copy()
    environment["WGPU_BACKEND"] = "dx12"
    environment["RUST_BACKTRACE"] = "full"
    process = subprocess.Popen(
        [str(helper), "--cdmw-session", str(session.manifest_path)],
        cwd=str(helper.parent),
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    messages: queue.Queue[dict[str, object] | str | None] = queue.Queue()
    stdout_thread = threading.Thread(
        target=_reader,
        args=(process.stdout, stdout_lines, messages),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_reader,
        args=(process.stderr, stderr_lines),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    observed: list[str] = []
    try:
        deadline = time.monotonic() + _HANDSHAKE_TIMEOUT_SECONDS
        while not {"hello", "ready"}.issubset(observed):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("helper handshake timed out")
            try:
                message = messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise AssertionError("helper handshake timed out") from exc
            if message is None:
                raise AssertionError(
                    "helper closed before ready:\n" + "\n".join(stderr_lines[-20:])
                )
            assert isinstance(message, dict), f"non-JSON helper stdout: {message!r}"
            assert message.get("protocol") == RUST_MESH_EDITOR_PROTOCOL
            assert message.get("session_id") == session.session_id
            assert message.get("process_generation") == session.process_generation
            event = str(message.get("event", ""))
            observed.append(event)
            if event == "hello":
                _write_host_message(
                    process,
                    session,
                    "hello",
                    request_id=0,
                    extra={"host": "cdmw-test", "status": "accepted"},
                )

        assert process.poll() is None
        time.sleep(0.25)
        assert process.poll() is None, "helper did not remain alive after ready"
        _write_host_message(
            process,
            session,
            "cancel",
            request_id=1,
            extra={"reason": "lifecycle regression complete"},
        )
        exit_code = process.wait(timeout=_EXIT_TIMEOUT_SECONDS)
        assert exit_code == 0, "helper cancel failed:\n" + "\n".join(
            stderr_lines[-20:]
        )
        return tuple(observed)
    finally:
        _stop_process(process, session)
        stdout_thread.join(timeout=2.0)
        stderr_thread.join(timeout=2.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def test_release_helper_can_cancel_and_reopen_twice_with_a_bc1_mip_tail(
    tmp_path: Path,
) -> None:
    helper = _release_helper()
    texture = tmp_path / "bc1-mip-tail.dds"
    texture.write_bytes(_bc1_mip_tail_dds())
    service, controller = _authoritative_controller(tmp_path, texture)
    session_ids: list[str] = []
    try:
        for generation in (1, 2):
            session = RustMeshAuthoringSession.create(
                controller,
                tmp_path / f"rust-session-{generation}",
                process_generation=generation,
                theme={"density": "compact"},
            )
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                assert manifest["texture_status"]["available"] is True
                assert manifest["texture_status"]["resource_count"] == 1
                resource = manifest["textures"][0]["file"]
                assert (session.root / resource["path"]).read_bytes() == texture.read_bytes()
                observed = _run_one_lifecycle(helper, session)
                assert observed[:2] == ("hello", "ready")
                session_ids.append(session.session_id)
            finally:
                session.cancel()
        assert len(set(session_ids)) == 2
        assert service.session_view(controller.active_session_id).revision == 0
    finally:
        service.close_edit_session(
            controller.active_session_id,
            force_without_saving=True,
        )
