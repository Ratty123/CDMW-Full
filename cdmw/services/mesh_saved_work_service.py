"""Saved Mesh Editor drafts and built mods: records, baselines and the list.

A draft is a Mesh Editor layer project inside a workspace folder under the
draft root, described by a ``modify_original_workspace.json`` manifest. Drafts
made by an archive session carry a copy of the mesh they started from, so a
later edit pass can be resumed after the in-session result has gone.

Built mods are listed in one index beside the drafts. A mod built from a
session with a draft keeps a frozen copy of that draft, so continuing it
restores the state it was built from. Drafts and built mods can carry a
name, notes and a user project from ``projects.json``. This module never
writes to game archives and never deletes a mod folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from uuid import uuid4

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry
from cdmw.services.atomic_file_service import atomic_write_text

WORKSPACE_MANIFEST_NAME = "modify_original_workspace.json"
WORKSPACE_MANIFEST_FORMAT = "cdmw_modify_original_workspace_v1"
DRAFT_ORIGIN = "mesh_editor_session"
DRAFT_MODE = "persistent_app_draft"
BUILT_MOD_DRAFT_MODE = "built_mod_draft"
PROJECT_RELATIVE_PATH = "mesh_layers/mesh_layer_project.json"
BASELINE_DIRNAME = "baseline"
BUILT_MODS_INDEX_NAME = "built_mods.json"
BUILT_MODS_INDEX_FORMAT = "cdmw_mesh_editor_built_mods_v1"
PROJECTS_INDEX_NAME = "projects.json"
PROJECTS_INDEX_FORMAT = "cdmw_mesh_editor_projects_v1"
MAX_NAME_LENGTH = 120
MAX_NOTES_LENGTH = 4000
KIND_DRAFT = "draft"
KIND_BUILT_MOD = "built_mod"
MAX_LISTED_ROWS = 2000
MAX_BASELINE_BYTES = 1024 * 1024 * 1024
_MESH_SUFFIXES = (".pac", ".pam", ".pamlod")
# Serializes every read-modify-write of saved-work JSON, including the
# autosave's manifest update, so a rename cannot be lost to a concurrent save.
SAVED_WORK_LOCK = threading.RLock()
_INDEX_LOCK = SAVED_WORK_LOCK

STATUS_CHECKING = "checking"
STATUS_MATCHES = "matches"
STATUS_GAME_UPDATED = "game_updated"
STATUS_SOURCE_MISSING = "source_missing"
STATUS_MOD_MISSING = "mod_missing"
STATUS_ORIGINAL_UNKNOWN = "original_unknown"
STATUS_GAME_NOT_LOADED = "game_not_loaded"


@dataclass(frozen=True, slots=True)
class MeshDraftRequest:
    """How the next archive session should save, and what it continues."""

    edit_pass: int = 1
    display_name: str = ""
    game_source_sha256: str = ""
    resume_manifest_path: Path | None = None
    seed_project_path: Path | None = None
    baseline_entries: tuple[ArchiveEntry, ...] = ()
    project_id: str = ""


@dataclass(frozen=True, slots=True)
class MeshDraftPlan:
    """A draft workspace that is created by the session's first save."""

    workspace_dir: Path
    manifest_path: Path
    project_path: Path
    manifest: Mapping[str, object]
    baseline_entries: tuple[ArchiveEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class SavedWorkRow:
    kind: str
    row_id: str
    display_name: str
    saved_at: float
    source_archive_path: str
    source_package: str
    edit_pass: int
    folder: Path
    manifest_path: Path | None
    source_sha256: str
    game_source_sha256: str
    has_draft: bool
    mod_root: Path | None = None
    project_id: str = ""
    notes: str = ""

    @property
    def is_built_mod(self) -> bool:
        return self.kind == KIND_BUILT_MOD


@dataclass(frozen=True, slots=True)
class SavedWorkProject:
    """A user's own grouping of drafts and built mods."""

    project_id: str
    name: str
    created_at: float = 0.0


def clean_name(value: object) -> str:
    """One line of text, as a name shown in the list."""

    return " ".join(str(value or "").split())[:MAX_NAME_LENGTH]


def clean_notes(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:MAX_NOTES_LENGTH]


def _clean_sha(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if len(text) == 64 and all(char in "0123456789abcdef" for char in text) else ""


def _positive_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _read_json(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _sha256_file(path: Path, stop_event: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            raise_if_cancelled(stop_event, "Saved work was cancelled.")
            digest.update(block)
    return digest.hexdigest()


def _slug(text: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text or "")).strip("-").lower()
    return stem[:40] or "mesh"


def default_display_name(archive_path: str) -> str:
    return PurePosixPath(str(archive_path or "").replace("\\", "/")).stem or "mesh"


def entry_record(entry: ArchiveEntry) -> dict[str, object]:
    """JSON fields that rebuild an archive location without its prepared copy."""

    return {
        "path": str(entry.path),
        "pamt_path": str(entry.pamt_path),
        "paz_file": str(entry.paz_file),
        "offset": int(entry.offset),
        "comp_size": int(entry.comp_size),
        "orig_size": int(entry.orig_size),
        "flags": int(entry.flags),
        "paz_index": int(entry.paz_index),
    }


def entry_from_record(record: Mapping[str, object]) -> ArchiveEntry:
    return ArchiveEntry(
        path=str(record.get("path") or ""),
        pamt_path=Path(str(record.get("pamt_path") or "")),
        paz_file=Path(str(record.get("paz_file") or "")),
        offset=int(record.get("offset") or 0),
        comp_size=int(record.get("comp_size") or 0),
        orig_size=int(record.get("orig_size") or 0),
        flags=int(record.get("flags") or 0),
        paz_index=int(record.get("paz_index") or 0),
    )


def _inside(root: Path, candidate: Path) -> bool:
    root = Path(root).resolve()
    resolved = Path(candidate).resolve()
    return resolved != root and root in resolved.parents


# ---------------------------------------------------------------- draft plans


def plan_session_draft(
    draft_root: Path | str,
    entry: ArchiveEntry,
    *,
    source_sha256: str,
    request: MeshDraftRequest | None = None,
    now: float | None = None,
) -> MeshDraftPlan:
    """Name a new draft folder; nothing is written until the first save."""

    request = request or MeshDraftRequest()
    source_hash = _clean_sha(source_sha256)
    if not source_hash:
        raise ValueError("A Mesh Editor draft needs the exact SHA-256 of its source mesh.")
    root = Path(draft_root).expanduser().resolve()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now if now is not None else time.time()))
    workspace = root / f"{_slug(default_display_name(entry.path))}-{stamp}-{uuid4().hex[:6]}"
    created = float(now if now is not None else time.time())
    manifest = {
        "format": WORKSPACE_MANIFEST_FORMAT,
        "draft_origin": DRAFT_ORIGIN,
        "workspace_mode": DRAFT_MODE,
        "display_name": str(request.display_name or default_display_name(entry.path)),
        "source_archive_path": str(entry.path),
        "source_package": entry.package_label,
        "source_entry": entry_record(entry),
        "source_asset_sha256": source_hash,
        "game_source_sha256": _clean_sha(request.game_source_sha256) or (
            source_hash if int(request.edit_pass) <= 1 else ""
        ),
        "edit_pass": max(1, int(request.edit_pass or 1)),
        "editable_obj": "",
        "mesh_layer_project": PROJECT_RELATIVE_PATH,
        "project_id": str(request.project_id or ""),
        "notes": "",
        "created_at": created,
        "updated_at": created,
    }
    return MeshDraftPlan(
        workspace_dir=workspace,
        manifest_path=workspace / WORKSPACE_MANIFEST_NAME,
        project_path=workspace / PROJECT_RELATIVE_PATH,
        manifest=manifest,
        baseline_entries=tuple(request.baseline_entries),
    )


def ensure_session_draft_workspace(
    plan: MeshDraftPlan,
    source_data: bytes,
    *,
    stop_event: threading.Event | None = None,
) -> Path:
    """Create the planned draft folder with its baseline copies, once."""

    manifest_path = Path(plan.manifest_path)
    if manifest_path.is_file():
        return manifest_path
    data = bytes(source_data or b"")
    if hashlib.sha256(data).hexdigest() != plan.manifest.get("source_asset_sha256"):
        raise ValueError("The draft's source mesh changed before it could be saved.")
    workspace = Path(plan.workspace_dir)
    baseline = workspace / BASELINE_DIRNAME
    baseline.mkdir(parents=True, exist_ok=True)
    source_name = PurePosixPath(str(plan.manifest.get("source_archive_path") or "source")).name or "source"
    mesh_file = baseline / f"00000-{source_name}"
    mesh_file.write_bytes(data)
    total = len(data)
    files: list[dict[str, object]] = []
    for index, entry in enumerate(plan.baseline_entries, start=1):
        raise_if_cancelled(stop_event, "Mesh layer autosave cancelled.")
        if entry.prepared_path is None:
            continue
        source = Path(entry.prepared_path)
        size = source.stat().st_size
        total += size
        if total > MAX_BASELINE_BYTES:
            raise ValueError("The draft's edited source files exceed the 1 GiB limit.")
        target = baseline / f"{index:05d}-{entry.basename}"
        shutil.copyfile(source, target)
        digest = _sha256_file(target, stop_event)
        if entry.prepared_sha256 and digest != entry.prepared_sha256.casefold():
            raise ValueError(f"An edited source file changed while saving the draft: {entry.path}")
        files.append({**entry_record(entry), "file": target.relative_to(workspace).as_posix(),
                      "sha256": digest, "size": size, "note": entry.prepared_note})
    raise_if_cancelled(stop_event, "Mesh layer autosave cancelled.")
    with SAVED_WORK_LOCK:
        manifest = dict(plan.manifest)
        manifest["baseline"] = {
            "mesh": mesh_file.relative_to(workspace).as_posix(),
            "mesh_sha256": manifest["source_asset_sha256"],
            "mesh_size": len(data),
            "files": files,
        }
        manifest["updated_at"] = time.time()
        atomic_write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True))
    return manifest_path


def read_draft_manifest(manifest_path: Path | str) -> Mapping[str, object] | None:
    payload = _read_json(Path(manifest_path))
    if payload is None or payload.get("format") != WORKSPACE_MANIFEST_FORMAT:
        return None
    return payload


def draft_lineage(manifest: Mapping[str, object] | None) -> dict[str, object]:
    """Fields a later edit pass inherits from the draft it continues."""

    if not manifest:
        return {}
    return {
        "display_name": str(manifest.get("display_name") or ""),
        "edit_pass": max(1, _positive_int(manifest.get("edit_pass"), 1)),
        "game_source_sha256": _clean_sha(manifest.get("game_source_sha256")),
        "project_id": str(manifest.get("project_id") or ""),
    }


def name_session_draft(
    manifest_path: Path | str | None,
    plan: MeshDraftPlan | None,
    *,
    name: str,
    project_id: str | None = None,
) -> None:
    """Name the draft an open session writes, before or after its first save."""

    cleaned = clean_name(name)
    if not cleaned:
        raise ValueError("Enter a name.")
    updates: dict[str, object] = {"display_name": cleaned}
    if project_id is not None:
        updates["project_id"] = str(project_id)
    with SAVED_WORK_LOCK:
        manifest = read_draft_manifest(manifest_path) if manifest_path is not None else None
        if manifest is not None:
            atomic_write_text(Path(manifest_path), json.dumps({**dict(manifest), **updates}, indent=2, sort_keys=True))
            return
        if plan is None:
            raise ValueError("This mesh has no draft yet.")
        # The planned manifest is written by the session's first save.
        plan.manifest.update(updates)


def draft_baseline_entries(
    manifest_path: Path | str,
    live_entry: ArchiveEntry | None = None,
    *,
    edited_note: str,
) -> tuple[ArchiveEntry, tuple[ArchiveEntry, ...]]:
    """Rebuild prepared archive entries from a draft's saved source copies.

    ``live_entry`` supplies the current archive location of the mesh. The saved
    location is used when the game no longer lists the file.
    """

    manifest_file = Path(manifest_path).resolve()
    manifest = read_draft_manifest(manifest_file)
    baseline = manifest.get("baseline") if manifest else None
    if not isinstance(baseline, Mapping):
        raise ValueError("This draft has no saved copy of its source mesh.")
    workspace = manifest_file.parent

    def saved_file(relative: object, expected_sha: object) -> tuple[Path, str, int]:
        path = (workspace / str(relative or "")).resolve()
        if not _inside(workspace, path) or not path.is_file():
            raise ValueError("A saved source file of this draft is missing.")
        digest = _sha256_file(path)
        if digest != _clean_sha(expected_sha):
            raise ValueError("A saved source file of this draft has been changed.")
        return path, digest, path.stat().st_size

    mesh_path, mesh_sha, mesh_size = saved_file(baseline.get("mesh"), baseline.get("mesh_sha256"))
    record = manifest.get("source_entry")
    base_entry = live_entry if live_entry is not None else (
        entry_from_record(record) if isinstance(record, Mapping) else None)
    if base_entry is None:
        raise ValueError("This draft does not record its game file location.")
    mesh_note = edited_note if _positive_int(manifest.get("edit_pass"), 1) > 1 else ""
    mesh_entry = replace(base_entry, prepared_path=mesh_path, prepared_sha256=mesh_sha,
                         prepared_size=mesh_size, prepared_note=mesh_note,
                         content_analysis_json_path=None, content_analysis_text_path=None,
                         content_analysis_version="")
    companions: list[ArchiveEntry] = []
    for item in baseline.get("files") or ():
        if not isinstance(item, Mapping):
            continue
        path, digest, size = saved_file(item.get("file"), item.get("sha256"))
        companions.append(replace(entry_from_record(item), prepared_path=path, prepared_sha256=digest,
                                  prepared_size=size, prepared_note=str(item.get("note") or edited_note)))
    return mesh_entry, tuple(companions)


# ------------------------------------------------------------------ the list


def _draft_row(workspace: Path) -> SavedWorkRow | None:
    manifest_path = workspace / WORKSPACE_MANIFEST_NAME
    manifest = read_draft_manifest(manifest_path)
    if manifest is None or str(manifest.get("workspace_mode") or "") != DRAFT_MODE:
        return None
    raw_project = str(manifest.get("mesh_layer_project") or PROJECT_RELATIVE_PATH)
    project = Path(raw_project)
    if not project.is_absolute():
        project = workspace / project
    if not project.is_file():
        return None
    source_hash = _clean_sha(manifest.get("source_asset_sha256"))
    if not source_hash:
        return None
    source_path = str(manifest.get("source_archive_path") or "")
    return SavedWorkRow(
        kind=KIND_DRAFT,
        row_id=workspace.name,
        display_name=str(manifest.get("display_name") or "") or default_display_name(source_path) or workspace.name,
        saved_at=_float(manifest.get("updated_at", manifest.get("created_at")), 0.0),
        source_archive_path=source_path,
        source_package=str(manifest.get("source_package") or ""),
        edit_pass=max(1, _positive_int(manifest.get("edit_pass"), 1)),
        folder=workspace,
        manifest_path=manifest_path.resolve(),
        source_sha256=source_hash,
        game_source_sha256=_clean_sha(manifest.get("game_source_sha256")),
        has_draft=True,
        project_id=str(manifest.get("project_id") or ""),
        notes=str(manifest.get("notes") or ""),
    )


def built_mods_index_path(draft_root: Path | str) -> Path:
    return Path(draft_root).expanduser().resolve() / BUILT_MODS_INDEX_NAME


def _read_index(draft_root: Path | str) -> list[dict[str, object]]:
    payload = _read_json(built_mods_index_path(draft_root))
    if payload is None or payload.get("format") != BUILT_MODS_INDEX_FORMAT:
        return []
    return [dict(item) for item in payload.get("mods") or () if isinstance(item, Mapping)]


def _write_index(draft_root: Path | str, records: Sequence[Mapping[str, object]]) -> None:
    path = built_mods_index_path(draft_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"format": BUILT_MODS_INDEX_FORMAT, "mods": list(records)},
                                       indent=2, sort_keys=True))


def _built_mod_row(draft_root: Path, record: Mapping[str, object]) -> SavedWorkRow | None:
    record_id = str(record.get("id") or "")
    raw_root = str(record.get("mod_root") or "")
    if not record_id or not raw_root:
        return None
    manifest_path = None
    raw_draft = str(record.get("draft_dir") or "")
    if raw_draft:
        candidate = (draft_root / raw_draft).resolve()
        if _inside(draft_root, candidate) and (candidate / WORKSPACE_MANIFEST_NAME).is_file():
            manifest_path = candidate / WORKSPACE_MANIFEST_NAME
    mod_root = Path(raw_root)
    return SavedWorkRow(
        kind=KIND_BUILT_MOD,
        row_id=record_id,
        display_name=str(record.get("display_name") or mod_root.name),
        saved_at=_float(record.get("built_at"), 0.0),
        source_archive_path=str(record.get("source_archive_path") or ""),
        source_package=str(record.get("source_package") or ""),
        edit_pass=_positive_int(record.get("edit_pass"), 0),
        folder=mod_root,
        manifest_path=manifest_path,
        source_sha256=_clean_sha(record.get("source_sha256")),
        game_source_sha256=_clean_sha(record.get("game_source_sha256")),
        has_draft=manifest_path is not None,
        mod_root=mod_root,
        project_id=str(record.get("project_id") or ""),
        notes=str(record.get("notes") or ""),
    )


def list_saved_work(draft_root: Path | str, *, path_filter: str = "") -> tuple[SavedWorkRow, ...]:
    """Every draft and indexed built mod, newest first. Reads small JSON only."""

    root = Path(draft_root).expanduser().resolve()
    rows: list[SavedWorkRow] = []
    if root.is_dir():
        for workspace in sorted(root.iterdir()):
            if len(rows) >= MAX_LISTED_ROWS:
                break
            if workspace.is_dir():
                row = _draft_row(workspace)
                if row is not None:
                    rows.append(row)
    for record in _read_index(root)[:MAX_LISTED_ROWS]:
        row = _built_mod_row(root, record)
        if row is not None:
            rows.append(row)
    wanted = str(path_filter or "").replace("\\", "/").strip().strip("/").casefold()
    if wanted:
        rows = [row for row in rows
                if row.source_archive_path.replace("\\", "/").strip("/").casefold() == wanted]
    return tuple(sorted(rows, key=lambda row: row.saved_at, reverse=True))


def saved_work_status(row: SavedWorkRow, *, found: bool, current_sha256: str = "") -> str:
    """Compare a row's original game file with the current game file."""

    if row.is_built_mod and (row.mod_root is None or not row.mod_root.is_dir()):
        return STATUS_MOD_MISSING
    if not found:
        return STATUS_SOURCE_MISSING
    current = _clean_sha(current_sha256)
    original = row.game_source_sha256 or (row.source_sha256 if row.edit_pass == 1 else "")
    if original:
        return STATUS_MATCHES if current == original else STATUS_GAME_UPDATED
    # A mod listed by hand may come from a later edit pass, so only a match
    # with its recorded source proves anything about the game file.
    return STATUS_MATCHES if current and current == row.source_sha256 else STATUS_ORIGINAL_UNKNOWN


def update_saved_work_details(
    draft_root: Path | str,
    row: SavedWorkRow,
    *,
    name: str | None = None,
    notes: str | None = None,
    project_id: str | None = None,
) -> None:
    """Change a row's name, notes or project. Folders keep their names."""

    updates: dict[str, object] = {}
    if name is not None:
        updates["display_name"] = clean_name(name)
        if not updates["display_name"]:
            raise ValueError("Enter a name.")
    if notes is not None:
        updates["notes"] = clean_notes(notes)
    if project_id is not None:
        updates["project_id"] = str(project_id)
    if not updates:
        return
    root = Path(draft_root).expanduser().resolve()
    with SAVED_WORK_LOCK:
        if row.is_built_mod:
            records = _read_index(root)
            for record in records:
                if str(record.get("id") or "") == row.row_id:
                    record.update(updates)
                    break
            else:
                raise ValueError("This built mod is no longer in the list.")
            _write_index(root, records)
            return
        manifest_path = Path(row.manifest_path or "")
        if not _inside(root, manifest_path.parent):
            raise ValueError("This draft is not in CDMW's draft folder.")
        manifest = read_draft_manifest(manifest_path)
        if manifest is None:
            raise ValueError("This draft can no longer be read.")
        atomic_write_text(manifest_path, json.dumps({**dict(manifest), **updates}, indent=2, sort_keys=True))


def rename_saved_work(draft_root: Path | str, row: SavedWorkRow, new_name: str) -> None:
    """Change the name shown in the list. Folders keep their names."""

    update_saved_work_details(draft_root, row, name=new_name)


def assign_project(draft_root: Path | str, rows: Sequence[SavedWorkRow], project_id: str) -> None:
    """Put drafts and built mods into a project, or into none with ``""``."""

    project = str(project_id or "")
    if project and project not in {item.project_id for item in list_projects(draft_root)}:
        raise ValueError("This project no longer exists.")
    for row in rows:
        update_saved_work_details(draft_root, row, project_id=project)


def projects_index_path(draft_root: Path | str) -> Path:
    return Path(draft_root).expanduser().resolve() / PROJECTS_INDEX_NAME


def _read_projects(draft_root: Path | str) -> list[dict[str, object]]:
    payload = _read_json(projects_index_path(draft_root))
    if payload is None or payload.get("format") != PROJECTS_INDEX_FORMAT:
        return []
    return [dict(item) for item in payload.get("projects") or ()
            if isinstance(item, Mapping) and str(item.get("id") or "")]


def _write_projects(draft_root: Path | str, records: Sequence[Mapping[str, object]]) -> None:
    path = projects_index_path(draft_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"format": PROJECTS_INDEX_FORMAT, "projects": list(records)},
                                       indent=2, sort_keys=True))


def list_projects(draft_root: Path | str) -> tuple[SavedWorkProject, ...]:
    projects = [SavedWorkProject(str(item["id"]), clean_name(item.get("name")) or "Project",
                                 _float(item.get("created_at"), 0.0))
                for item in _read_projects(draft_root)]
    return tuple(sorted(projects, key=lambda project: project.name.casefold()))


def _require_unique_project_name(records: Sequence[Mapping[str, object]], name: str, skip: str = "") -> None:
    if any(str(item.get("id")) != skip and clean_name(item.get("name")).casefold() == name.casefold()
           for item in records):
        raise ValueError("A project with this name already exists.")


def create_project(draft_root: Path | str, name: str) -> SavedWorkProject:
    cleaned = clean_name(name)
    if not cleaned:
        raise ValueError("Enter a name.")
    with SAVED_WORK_LOCK:
        records = _read_projects(draft_root)
        _require_unique_project_name(records, cleaned)
        project = SavedWorkProject(uuid4().hex, cleaned, time.time())
        records.append({"id": project.project_id, "name": project.name, "created_at": project.created_at})
        _write_projects(draft_root, records)
    return project


def rename_project(draft_root: Path | str, project_id: str, name: str) -> None:
    cleaned = clean_name(name)
    if not cleaned:
        raise ValueError("Enter a name.")
    with SAVED_WORK_LOCK:
        records = _read_projects(draft_root)
        _require_unique_project_name(records, cleaned, skip=str(project_id))
        for record in records:
            if str(record.get("id")) == str(project_id):
                record["name"] = cleaned
                break
        else:
            raise ValueError("This project no longer exists.")
        _write_projects(draft_root, records)


def delete_project(draft_root: Path | str, project_id: str) -> None:
    """Remove a project. Its drafts and built mods stay, with no project."""

    project = str(project_id or "")
    root = Path(draft_root).expanduser().resolve()
    with SAVED_WORK_LOCK:
        records = _read_projects(root)
        kept = [record for record in records if str(record.get("id")) != project]
        if len(kept) == len(records):
            raise ValueError("This project no longer exists.")
        for row in list_saved_work(root):
            if row.project_id == project:
                update_saved_work_details(root, row, project_id="")
        _write_projects(root, kept)


def duplicate_saved_draft(draft_root: Path | str, row: SavedWorkRow, name: str) -> Path:
    """Copy a draft into a new one with its own name, to try a variation."""

    if row.is_built_mod or row.manifest_path is None:
        raise ValueError("Only drafts can be duplicated.")
    cleaned = clean_name(name)
    if not cleaned:
        raise ValueError("Enter a name.")
    root = Path(draft_root).expanduser().resolve()
    source = Path(row.manifest_path).resolve().parent
    if not _inside(root, source):
        raise ValueError("This draft is not in CDMW's draft folder.")
    manifest = read_draft_manifest(source / WORKSPACE_MANIFEST_NAME)
    if manifest is None:
        raise ValueError("This draft can no longer be read.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = root / f"{_slug(cleaned)}-{stamp}-{uuid4().hex[:6]}"
    try:
        _copy_draft(source, target, None)
        now = time.time()
        atomic_write_text(target / WORKSPACE_MANIFEST_NAME, json.dumps({
            **dict(manifest), "display_name": cleaned, "created_at": now, "updated_at": now,
            "mesh_layer_project": PROJECT_RELATIVE_PATH}, indent=2, sort_keys=True))
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target / WORKSPACE_MANIFEST_NAME


def _remove_owned_draft(root: Path, workspace: Path) -> None:
    workspace = Path(workspace).resolve()
    if not _inside(root, workspace) or workspace.parent != root:
        raise ValueError("This draft is not in CDMW's draft folder.")
    if read_draft_manifest(workspace / WORKSPACE_MANIFEST_NAME) is None:
        raise ValueError("This folder is not a Mesh Editor draft.")
    shutil.rmtree(workspace)


def delete_saved_draft(draft_root: Path | str, row: SavedWorkRow) -> None:
    if row.is_built_mod:
        raise ValueError("Built mods are removed from the list, never deleted here.")
    _remove_owned_draft(Path(draft_root).expanduser().resolve(), row.folder)


def remove_built_mod_from_list(draft_root: Path | str, row: SavedWorkRow) -> None:
    """Forget a built mod and its saved editing state. The mod folder is kept."""

    if not row.is_built_mod:
        raise ValueError("Only built mods can be removed from the list.")
    root = Path(draft_root).expanduser().resolve()
    with _INDEX_LOCK:
        records = _read_index(root)
        kept = [record for record in records if str(record.get("id") or "") != row.row_id]
        _write_index(root, kept)
    if row.manifest_path is not None:
        _remove_owned_draft(root, Path(row.manifest_path).parent)


# ------------------------------------------------------------- built mods


def _copy_draft(source_workspace: Path, target_workspace: Path, stop_event) -> None:
    """Copy a draft with its baseline and newest generations only."""

    source_workspace = Path(source_workspace)
    project_dir = source_workspace / PurePosixPath(PROJECT_RELATIVE_PATH).parent
    descriptor = _read_json(source_workspace / PROJECT_RELATIVE_PATH) or {}
    keep = {str(descriptor.get("current_generation") or ""), str(descriptor.get("previous_generation") or "")}
    target_workspace.mkdir(parents=True, exist_ok=False)
    for path in sorted(source_workspace.rglob("*")):
        raise_if_cancelled(stop_event, "Saved work was cancelled.")
        relative = path.relative_to(source_workspace)
        if path.is_symlink():
            raise ValueError("A draft cannot contain linked files.")
        if (relative.parts and project_dir.name == relative.parts[0] and len(relative.parts) > 1
                and relative.parts[1].startswith("generation-") and relative.parts[1] not in keep):
            continue
        target = target_workspace / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def register_built_mod(
    draft_root: Path | str,
    *,
    mod_root: Path | str,
    entry: ArchiveEntry,
    source_sha256: str,
    draft_manifest_path: Path | str | None,
    zip_path: Path | str | None = None,
    manager_profile: str = "",
    kind: str = "",
    stop_event: threading.Event | None = None,
) -> dict[str, object]:
    """Index a finished mod and freeze the draft it was built from."""

    root = Path(draft_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    record_id = uuid4().hex
    mod_root = Path(mod_root).resolve()
    lineage: dict[str, object] = {"edit_pass": 1, "game_source_sha256": "", "display_name": ""}
    draft_dir = ""
    if draft_manifest_path is not None:
        source_manifest = Path(draft_manifest_path).resolve()
        manifest = read_draft_manifest(source_manifest)
        if manifest is None:
            raise ValueError("This draft can no longer be read.")
        lineage = draft_lineage(manifest)
        frozen = root / f"built-{_slug(mod_root.name)}-{record_id[:8]}"
        try:
            _copy_draft(source_manifest.parent, frozen, stop_event)
            atomic_write_text(frozen / WORKSPACE_MANIFEST_NAME, json.dumps({
                **dict(manifest), "workspace_mode": BUILT_MOD_DRAFT_MODE,
                "mesh_layer_project": PROJECT_RELATIVE_PATH, "built_mod_id": record_id,
                "updated_at": time.time()}, indent=2, sort_keys=True))
        except BaseException:
            shutil.rmtree(frozen, ignore_errors=True)
            raise
        draft_dir = frozen.name
    record = {
        "id": record_id,
        "display_name": mod_root.name,
        "mod_root": str(mod_root),
        "zip_path": str(zip_path or ""),
        "built_at": time.time(),
        "manager_profile": str(manager_profile or ""),
        "output_kind": str(kind or ""),
        "source_archive_path": str(entry.path),
        "source_package": entry.package_label,
        "source_entry": entry_record(entry),
        "source_sha256": _clean_sha(source_sha256),
        "game_source_sha256": lineage["game_source_sha256"] or (
            _clean_sha(source_sha256) if lineage["edit_pass"] == 1 else ""),
        "edit_pass": lineage["edit_pass"],
        "draft_dir": draft_dir,
        "project_id": str(lineage.get("project_id") or ""),
        "notes": "",
    }
    with _INDEX_LOCK:
        records = _read_index(root)
        records.append(record)
        _write_index(root, records)
    return record


def _mesh_files(mod_root: Path, limit: int = 4096) -> list[Path]:
    found: list[Path] = []
    for current, dirs, files in os.walk(mod_root):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in files:
            if name.casefold().endswith(_MESH_SUFFIXES):
                found.append(Path(current) / name)
                if len(found) >= limit:
                    return found
    return found


def _guess_archive_path(relative: PurePosixPath) -> str:
    parts = list(relative.parts)
    if parts and parts[0].casefold() == "files":
        parts = parts[1:]
    if parts and parts[0].isdigit():
        parts = parts[1:]
    return "/".join(parts)


def add_built_mod_folder(draft_root: Path | str, mod_root: Path | str, *, project_id: str = "") -> dict[str, object]:
    """List a mod folder made before saved drafts existed, or by someone else."""

    from cdmw.core.mod_export_history import mod_metadata_path

    folder = Path(mod_root).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("Choose an existing mod folder.")
    root = Path(draft_root).expanduser().resolve()
    with _INDEX_LOCK:
        if any(Path(str(record.get("mod_root") or "")).resolve() == folder for record in _read_index(root)):
            raise ValueError("This mod folder is already in the list.")
    metadata = _read_json(mod_metadata_path(folder, "mesh-editor-session.json")) or {}
    source_path = str(metadata.get("source_path") or "").replace("\\", "/").strip("/")
    if not source_path:
        meshes = _mesh_files(folder, limit=1)
        candidates = ([_guess_archive_path(PurePosixPath(meshes[0].relative_to(folder).as_posix()))]
                      if meshes else _archive_group_mesh_paths(folder))
        source_path = candidates[0] if candidates else ""
    if not source_path:
        raise ValueError("This folder contains no mesh files.")
    record = {
        "id": uuid4().hex,
        "display_name": folder.name,
        "mod_root": str(folder),
        "zip_path": "",
        "built_at": folder.stat().st_mtime,
        "manager_profile": "",
        "output_kind": "added_folder",
        "source_archive_path": source_path,
        "source_package": "",
        "source_entry": {},
        "source_sha256": _clean_sha(metadata.get("source_sha256")),
        "game_source_sha256": "",
        "edit_pass": 0,
        "draft_dir": "",
        "project_id": str(project_id or ""),
        "notes": "",
    }
    with _INDEX_LOCK:
        records = _read_index(root)
        records.append(record)
        _write_index(root, records)
    return record


def _archive_group_mesh_paths(mod_root: Path) -> list[str]:
    from cdmw.core.archive_format import parse_archive_pamt

    paths: list[str] = []
    for pamt in sorted(Path(mod_root).glob("*/0.pamt")):
        try:
            entries = parse_archive_pamt(pamt)
        except Exception:
            continue
        paths.extend(entry.path for entry in entries if entry.path.casefold().endswith(_MESH_SUFFIXES))
    return paths


def read_built_mod_mesh(
    mod_root: Path | str,
    archive_path: str,
    *,
    stop_event: threading.Event | None = None,
) -> bytes:
    """Read the finished mesh for ``archive_path`` from a loose or DMM mod folder."""

    folder = Path(mod_root).resolve()
    if not folder.is_dir():
        raise ValueError("The mod folder no longer exists.")
    wanted = str(archive_path or "").replace("\\", "/").strip("/").casefold()
    for candidate in _mesh_files(folder):
        raise_if_cancelled(stop_event, "Saved work was cancelled.")
        relative = candidate.relative_to(folder).as_posix().casefold()
        if relative == wanted or relative.endswith("/" + wanted):
            return candidate.read_bytes()
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.archive_read_service import read_archive_entry_data

    for pamt in sorted(folder.glob("*/0.pamt")):
        raise_if_cancelled(stop_event, "Saved work was cancelled.")
        try:
            entries = parse_archive_pamt(pamt)
        except Exception:
            continue
        for entry in entries:
            if entry.path.replace("\\", "/").strip("/").casefold() == wanted:
                return read_archive_entry_data(entry, stop_event=stop_event)[0]
    raise ValueError("The mod folder no longer contains the edited mesh.")


def save_built_mod_mesh_copy(
    draft_root: Path | str,
    row: SavedWorkRow,
    data: bytes,
) -> Path:
    """Keep the finished mesh that starts a new edit pass beside the drafts."""

    root = Path(draft_root).expanduser().resolve() / "built_mod_meshes"
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    target = root / f"{digest[:16]}-{PurePosixPath(row.source_archive_path).name or 'mesh'}"
    if not target.is_file() or _sha256_file(target) != digest:
        temporary = target.with_name(target.name + f".{uuid4().hex[:8]}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
    return target


@dataclass(frozen=True, slots=True)
class SavedWorkLaunch:
    """What to open for Continue editing, prepared off the UI thread."""

    row: SavedWorkRow
    selected_entry: ArchiveEntry
    replacements: tuple[ArchiveEntry, ...]
    resume_manifest_path: Path | None
    draft_request: MeshDraftRequest
    game_updated: bool = False


def prepare_saved_work_launch(
    draft_root: Path | str,
    row: SavedWorkRow,
    live_entry: ArchiveEntry,
    *,
    edited_note: str,
    stop_event: threading.Event | None = None,
) -> SavedWorkLaunch:
    """Choose the source bytes and draft for continuing ``row`` over ``live_entry``.

    ``live_entry`` is the current game file at the row's path. Saved copies
    replace its bytes when the draft started from a different version.
    """

    from cdmw.services.archive_read_service import read_archive_entry_data

    current = hashlib.sha256(read_archive_entry_data(live_entry, stop_event=stop_event)[0]).hexdigest()
    game_updated = saved_work_status(row, found=True, current_sha256=current) == STATUS_GAME_UPDATED
    if row.is_built_mod and row.manifest_path is None:
        data = read_built_mod_mesh(row.mod_root or row.folder, row.source_archive_path, stop_event=stop_event)
        copy_path = save_built_mod_mesh_copy(draft_root, row, data)
        selected = replace(live_entry, prepared_path=copy_path, prepared_sha256=hashlib.sha256(data).hexdigest(),
                           prepared_size=len(data), prepared_note=edited_note, content_analysis_json_path=None,
                           content_analysis_text_path=None, content_analysis_version="")
        request = MeshDraftRequest(edit_pass=max(1, row.edit_pass) + 1, display_name=row.display_name,
                                   game_source_sha256=row.game_source_sha256, project_id=row.project_id)
        return SavedWorkLaunch(row, selected, (selected,), None, request, game_updated)
    manifest = read_draft_manifest(row.manifest_path or "")
    if manifest is None:
        raise ValueError("This draft can no longer be read.")
    lineage = draft_lineage(manifest)
    project = Path(str(manifest.get("mesh_layer_project") or PROJECT_RELATIVE_PATH))
    if not project.is_absolute():
        project = Path(row.manifest_path).parent / project
    if not row.is_built_mod and lineage["edit_pass"] == 1 and current == row.source_sha256:
        request = MeshDraftRequest(edit_pass=1, display_name=row.display_name,
                                   game_source_sha256=lineage["game_source_sha256"],
                                   resume_manifest_path=row.manifest_path, project_id=row.project_id)
        return SavedWorkLaunch(row, live_entry, (), row.manifest_path, request, game_updated)
    if not isinstance(manifest.get("baseline"), Mapping):
        raise ValueError(
            "This draft was made from another version of the game file and has no saved copy of it."
        )
    selected, companions = draft_baseline_entries(row.manifest_path, live_entry, edited_note=edited_note)
    if row.is_built_mod:
        # Continue in a new draft, so the mod's own saved state stays as built.
        request = MeshDraftRequest(edit_pass=lineage["edit_pass"], display_name=row.display_name,
                                   game_source_sha256=lineage["game_source_sha256"],
                                   seed_project_path=project.resolve(), baseline_entries=companions,
                                   project_id=row.project_id)
        return SavedWorkLaunch(row, selected, (selected, *companions), None, request, game_updated)
    request = MeshDraftRequest(edit_pass=lineage["edit_pass"], display_name=row.display_name,
                               game_source_sha256=lineage["game_source_sha256"],
                               resume_manifest_path=row.manifest_path, project_id=row.project_id)
    return SavedWorkLaunch(row, selected, (selected, *companions), row.manifest_path, request, game_updated)


__all__ = [
    "BUILT_MOD_DRAFT_MODE",
    "DRAFT_MODE",
    "DRAFT_ORIGIN",
    "KIND_BUILT_MOD",
    "KIND_DRAFT",
    "MeshDraftPlan",
    "MeshDraftRequest",
    "SAVED_WORK_LOCK",
    "STATUS_CHECKING",
    "STATUS_GAME_NOT_LOADED",
    "STATUS_GAME_UPDATED",
    "STATUS_MATCHES",
    "STATUS_MOD_MISSING",
    "STATUS_ORIGINAL_UNKNOWN",
    "STATUS_SOURCE_MISSING",
    "SavedWorkLaunch",
    "SavedWorkProject",
    "SavedWorkRow",
    "add_built_mod_folder",
    "assign_project",
    "clean_name",
    "clean_notes",
    "create_project",
    "default_display_name",
    "delete_project",
    "delete_saved_draft",
    "draft_baseline_entries",
    "draft_lineage",
    "duplicate_saved_draft",
    "ensure_session_draft_workspace",
    "entry_from_record",
    "entry_record",
    "list_projects",
    "list_saved_work",
    "name_session_draft",
    "plan_session_draft",
    "prepare_saved_work_launch",
    "read_built_mod_mesh",
    "read_draft_manifest",
    "register_built_mod",
    "remove_built_mod_from_list",
    "rename_project",
    "rename_saved_work",
    "save_built_mod_mesh_copy",
    "saved_work_status",
    "update_saved_work_details",
]
