"""Worker-side launch preparation for the optional New Item Rust presentation."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_CONTROL_CONTRACT_FILE, resolve_rust_mesh_editor, validate_rust_mesh_editor_package,
)
from cdmw.services.new_item_rust_protocol import PROTOCOL


@dataclass(frozen=True)
class NewItemUiLaunch:
    executable: str
    root: Path
    manifest: Path

    def cleanup(self):
        # Only the two paths created here are owned. Never recursively remove a
        # renderer-supplied path or an arbitrary session tree.
        self.manifest.unlink(missing_ok=True)
        self.root.rmdir()


def prepare_new_item_ui(session, _log, stop_event):
    raise_if_cancelled(stop_event, "New Item UI startup cancelled.")
    resolution = resolve_rust_mesh_editor()
    reason = validate_rust_mesh_editor_package(resolution)
    if reason:
        raise RuntimeError(f"The Rust New Item interface cannot start: {reason}.")
    # This optional capability lives in the executable's hashed control contract.
    # Existing Mesh Editor packages remain valid for their original callers.
    contract_path = Path(resolution.resolved_path).with_name(RUST_MESH_CONTROL_CONTRACT_FILE)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    capability = contract.get("new_item_ui") if isinstance(contract, dict) else None
    if not isinstance(capability, dict) or capability.get("protocol") != PROTOCOL:
        raise RuntimeError("The installed Rust helper does not contain the New Item interface. Rebuild the native helpers before opening this tool.")
    raise_if_cancelled(stop_event, "New Item UI startup cancelled.")
    root = Path(tempfile.mkdtemp(prefix="cdmw-new-item-ui-"))
    manifest = root / "session.json"
    launch = NewItemUiLaunch(resolution.resolved_path, root, manifest)
    try:
        manifest.write_text(json.dumps({"protocol": PROTOCOL, "session": session}), encoding="utf-8")
        raise_if_cancelled(stop_event, "New Item UI startup cancelled.")
        return launch
    except BaseException:
        launch.cleanup()
        raise
