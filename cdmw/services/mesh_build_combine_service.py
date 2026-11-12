"""Combine two or more built Mesh Editor mods into one mod (GitHub issue 31).

`prepare_mesh_build_combine` reads the selected build folders and plans the
combination; it writes nothing. `export_combined_mesh_builds` writes a new mod
folder from that plan. The selected builds are never changed, and nothing is
written into the game: the output is a mod like any other build.

Two routes, chosen by `combined_output_layout`:
- Loose builds for one manager become one loose mod, written by the loose-mod
  writer, so its manifest counts and every file's package group come from the
  writer itself and are right by construction.
- Anything else (an archive-group build, or builds for different managers)
  goes through the existing merge service (`prepare_mod_merge`,
  `export_merged_mod`) and becomes a DMM archive group. Mod Management's folder
  tools stay off; only that service is reused.

Both routes refuse before writing when two builds write the same game file,
with the file and the builds named.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Sequence

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.packages.mesh_build_combine import (
    LAYOUT_ARCHIVE_GROUP,
    LAYOUT_LOOSE,
    MeshBuildCombinePlan,
    MeshBuildFile,
    MeshBuildSource,
    normalize_game_path,
    plan_mesh_build_combine,
)

SESSION_METADATA = "mesh-editor-session.json"
COMBINED_METADATA_FORMAT = "cdmw_mesh_editor_combined_v1"
_MAX_JSON_BYTES = 8 * 1024 * 1024
_CANCELLED = "Combining built mods was cancelled."


@dataclass(frozen=True, slots=True)
class PreparedMeshBuildCombine:
    """A reviewed combination and where each file's bytes come from."""

    plan: MeshBuildCombinePlan
    #: (build label, normalized game path) -> loose file or archive entry inside that build.
    payloads: Mapping[tuple[str, str], object]

    @property
    def can_combine(self) -> bool:
        return self.plan.can_combine

    @property
    def refusal(self) -> str:
        return self.plan.refusal


@dataclass(frozen=True, slots=True)
class CombinedMeshBuildResult:
    output_path: Path
    zip_path: Path | None
    layout: str
    manager_profile: str
    target_paths: tuple[str, ...]
    combined_from: tuple[str, ...]


# ------------------------------------------------------------------ reading


def _read_small_json(path: Path) -> Mapping[str, object] | None:
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > _MAX_JSON_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _session_metadata(folder: Path, stop_event) -> Mapping[str, object]:
    from cdmw.core.mod_export_history import mod_metadata_path

    return _read_small_json(mod_metadata_path(folder, SESSION_METADATA, stop_event=stop_event)) or {}


def _manager_profile(folder: Path, manifest: Mapping[str, object], session: Mapping[str, object]) -> str:
    profile = str(session.get("manager_profile") or "").strip().casefold()
    if profile in {"dmm", "cdumm"}:
        return profile
    targets = manifest.get("manager_targets")
    if isinstance(targets, list) and targets:
        first = str(targets[0]).strip().casefold()
        if first in {"dmm", "cdumm"}:
            return first
    if (folder / "files").is_dir() and (folder / "modinfo.json").is_file() and not (folder / "manifest.json").is_file():
        return "cdumm"
    return "dmm"


def _manifest_rows(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows: dict[str, Mapping[str, object]] = {}
    for item in manifest.get("files") or ():
        if isinstance(item, Mapping) and item.get("path"):
            try:
                rows.setdefault(normalize_game_path(item["path"]), item)
            except ValueError:
                continue
    for item in manifest.get("assets") or ():
        if isinstance(item, Mapping) and item.get("entry_path"):
            try:
                rows.setdefault(normalize_game_path(item["entry_path"]), item)
            except ValueError:
                continue
    return rows


def _payload_bytes(payload, stop_event) -> bytes:
    raise_if_cancelled(stop_event, _CANCELLED)
    if getattr(payload, "entry", None) is not None:
        from cdmw.core.archive_extraction import read_archive_entry_data

        return read_archive_entry_data(payload.entry)[0]
    return Path(payload.path).read_bytes()


def _original_case_path(payload, key: str, rows: Mapping[str, Mapping[str, object]]) -> str:
    row = rows.get(key)
    if row is not None:
        value = str(row.get("path") or row.get("entry_path") or "").replace("\\", "/").strip("/")
        if value:
            return value
    entry = getattr(payload, "entry", None)
    if entry is not None and getattr(entry, "path", ""):
        return str(entry.path).replace("\\", "/").strip("/")
    return key


def read_mesh_build(
    folder: Path | str,
    *,
    label: str = "",
    stop_event: threading.Event | None = None,
) -> tuple[MeshBuildSource, dict[str, object]]:
    """Describe one built mod folder; returns the source and its payloads by game path.

    Reads the folder only. Loose layouts (game-relative or under `files/`) and
    DMM archive groups are both read; a semantic export or field JSON is refused
    by the shared folder reader.
    """

    from cdmw.core.mod_compatibility import build_label, read_compatibility
    from cdmw.services.new_item_mod_base import mod_folder_payloads

    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"The built mod folder no longer exists: {root}")
    label = str(label or root.name)
    payloads = mod_folder_payloads(root, stop_event=stop_event)
    if not payloads:
        raise ValueError(f'"{label}" contains no mod files.')
    manifest = _read_small_json(root / "manifest.json") or {}
    session = _session_metadata(root, stop_event)
    rows = _manifest_rows(manifest)
    layout = LAYOUT_ARCHIVE_GROUP if any(getattr(item, "entry", None) is not None for item in payloads.values()) \
        else LAYOUT_LOOSE
    files: list[MeshBuildFile] = []
    by_key: dict[str, object] = {}
    for raw_key, payload in sorted(payloads.items()):
        raise_if_cancelled(stop_event, _CANCELLED)
        key = normalize_game_path(raw_key)
        if key == "meta/0.papgt":
            continue  # Each manager rebuilds its own mount list.
        data = _payload_bytes(payload, stop_event)
        row = rows.get(key) or {}
        path = _original_case_path(payload, key, rows)
        entry = getattr(payload, "entry", None)
        group = str(row.get("package_group") or "")
        files.append(MeshBuildFile(
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            package_group=group,
            format=str(row.get("format") or PurePosixPath(path).suffix.lstrip(".")).casefold(),
            note=str(row.get("note") or ""),
            is_new=bool(row.get("is_new")),
        ))
        by_key[key] = payload if entry is None else payload
    compatibility = None
    try:
        compatibility = read_compatibility(root, stop_event=stop_event)
    except (OSError, ValueError):
        compatibility = None
    game_build = build_label(compatibility.target_game) if compatibility is not None else ""
    if game_build == "Unknown":
        game_build = ""
    formats = tuple(str(value) for value in (session.get("format"),) if value)
    source = MeshBuildSource(
        label=label,
        folder=str(root),
        layout=layout,
        manager_profile=_manager_profile(root, manifest, session),
        files=tuple(files),
        title=str(manifest.get("title") or manifest.get("name") or root.name),
        target_game_build=game_build,
        session_formats=formats,
    )
    return source, by_key


def prepare_mesh_build_combine(
    folders: Sequence[Path | str],
    *,
    labels: Sequence[str] = (),
    stop_event: threading.Event | None = None,
) -> PreparedMeshBuildCombine:
    """Read the selected builds and plan their combination. Writes nothing.

    `labels` name the builds in messages (the Drafts & Mods row names); the
    folder name is used where none is given. A conflict does not raise: it is
    in `refusal`, so the caller can show it before anything is written.
    """

    folders = tuple(folders)
    names = list(labels) + [""] * (len(folders) - len(labels))
    sources: list[MeshBuildSource] = []
    payloads: dict[tuple[str, str], object] = {}
    used: set[str] = set()
    for folder, name in zip(folders, names):
        label = str(name or Path(folder).name)
        if label.casefold() in used:
            label = str(Path(folder).expanduser().resolve())
        used.add(label.casefold())
        source, by_key = read_mesh_build(folder, label=label, stop_event=stop_event)
        sources.append(source)
        payloads.update({(source.label, key): value for key, value in by_key.items()})
    return PreparedMeshBuildCombine(plan_mesh_build_combine(sources), payloads)


# ------------------------------------------------------------------ writing


def _check_destination(prepared: PreparedMeshBuildCombine, root: Path, game_root: Path | None) -> None:
    sources = [Path(source.folder) for source in prepared.plan.sources]
    if game_root is not None:
        sources.append(Path(game_root).resolve())
    for source in sources:
        if root == source or root.is_relative_to(source) or source.is_relative_to(root):
            raise ValueError("Choose an output folder separate from the game and every selected build.")
    if root.exists() or root.is_symlink():
        if not root.is_dir() or any(root.iterdir()):
            raise ValueError("Choose a new or empty output folder. The selected builds are kept as they are.")


def _verify_unchanged(prepared: PreparedMeshBuildCombine, stop_event) -> dict[tuple[str, str], bytes]:
    """Re-read every planned file and refuse when a build changed since it was reviewed."""

    current: dict[tuple[str, str], bytes] = {}
    for item, label in prepared.plan.files:
        key = (label, item.key)
        payload = prepared.payloads.get(key)
        if payload is None:
            raise ValueError(f'"{label}" no longer lists {item.path}. Check the builds again.')
        data = _payload_bytes(payload, stop_event)
        if hashlib.sha256(data).hexdigest() != item.sha256:
            raise ValueError(f'"{label}" changed since it was checked: {item.path}. Check the builds again.')
        current[key] = data
    return current


def _combined_metadata(prepared: PreparedMeshBuildCombine) -> bytes:
    plan = prepared.plan
    payload = {
        "format": COMBINED_METADATA_FORMAT,
        "manager_profile": plan.manager_profile,
        "layout": plan.layout,
        "combined_from": [
            {"label": source.label, "folder": source.folder, "target_paths": list(source.target_paths)}
            for source in plan.sources
        ],
        "assets": [
            {"path": item.path, "package_group": item.package_group, "from": label}
            for item, label in plan.files if item.is_mesh_target
        ],
        "shared_companions": list(plan.shared_companions),
        "contents": ["combined_mesh_editor_builds"],
    }
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def merge_build_compatibility(folders: Iterable[Path | str], paths: Iterable[str], *, stop_event=None):
    """One compatibility record for the combined mod from the builds' own records.

    The payload bytes are copied unchanged, so each build's record of what it
    replaces still holds for those files. Returns None when no build has one.
    """

    from cdmw.core.mod_compatibility import ModCompatibility, payload_path, read_compatibility

    wanted = {payload_path(path) for path in paths}
    target_game: dict = {}
    records: dict[str, dict] = {}
    originals: dict[str, bytes | None] = {}
    dependencies: dict[str, dict] = {}
    found = False
    for folder in folders:
        try:
            evidence = read_compatibility(Path(folder), stop_event=stop_event)
        except (OSError, ValueError):
            evidence = None
        if evidence is None:
            continue
        found = True
        if not target_game and evidence.target_game:
            target_game = dict(evidence.target_game)
        for record in evidence.files:
            path = payload_path(record.get("path", ""))
            if path in wanted and path not in records:
                records[path] = dict(record, path=path)
                if path in evidence.originals:
                    originals[path] = evidence.originals[path]
        for item in evidence.dependencies:
            dependencies.setdefault(payload_path(item.get("path", "")), dict(item))
    if not found:
        return None
    return ModCompatibility(target_game, tuple(records[path] for path in sorted(records)), originals,
                            tuple(dependencies[path] for path in sorted(dependencies)))


def _write_loose(prepared: PreparedMeshBuildCombine, root: Path, data: Mapping[tuple[str, str], bytes], *,
                 package_info, create_zip: bool, stop_event) -> Path | None:
    from cdmw.core.atomic_file import atomic_write_bytes
    from cdmw.core.mod_package import MeshLooseModAsset, MeshLooseModFile, write_mesh_loose_mod_package_metadata
    from cdmw.domain.packages.export_policy import mod_package_export_options_for_manager
    from cdmw.services.mesh_mod_publish import publish_mesh_mod_output

    plan = prepared.plan
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.staging-", dir=root.parent))
    try:
        assets, files = [], []
        for item, label in plan.files:
            raise_if_cancelled(stop_event, _CANCELLED)
            relative = PurePosixPath(item.path)
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, data[(label, item.key)])
            note = item.note or ("Validated Mesh Editor replacement" if item.is_mesh_target else "Replacement companion")
            if item.is_mesh_target:
                assets.append(MeshLooseModAsset(entry_path=item.path, package_group=item.package_group,
                                                format=item.format, note=note))
            files.append(MeshLooseModFile(path=item.path, package_group=item.package_group, format=item.format,
                                          is_new=item.is_new, note=note))
        atomic_write_bytes(staging / SESSION_METADATA, _combined_metadata(prepared))
        options = mod_package_export_options_for_manager(plan.manager_profile)
        compatibility = merge_build_compatibility((source.folder for source in plan.sources),
                                                  (item.path for item, _label in plan.files), stop_event=stop_event)
        write_mesh_loose_mod_package_metadata(
            staging, package_info, assets=tuple(assets), files=tuple(files), include_paired_lod=False,
            export_options=options, create_no_encrypt_file=bool(options.create_no_encrypt_file),
            compatibility=compatibility, stop_event=stop_event,
        )
        return publish_mesh_mod_output(staging, root, manager_profile=plan.manager_profile,
                                       create_zip=create_zip, stop_event=stop_event)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def export_combined_mesh_builds(
    prepared: PreparedMeshBuildCombine,
    destination: Path | str,
    *,
    title: str = "Combined mod",
    package_info=None,
    create_zip: bool = False,
    game_root: Path | str | None = None,
    entries: Iterable = (),
    read_entry: Callable | None = None,
    on_log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> CombinedMeshBuildResult:
    """Write the combined mod to a new folder. Refuses on any conflict, before writing.

    The archive-group route needs the loaded game (`game_root` and its catalogue
    `entries`), as the merge service it reuses does; the loose route needs neither.
    """

    from cdmw.models import ModPackageInfo

    if not prepared.can_combine:
        raise ValueError(prepared.refusal)
    plan = prepared.plan
    root = Path(destination).expanduser().resolve()
    game = Path(game_root).expanduser().resolve() if game_root is not None else None
    _check_destination(prepared, root, game)
    title = str(title or "").strip() or "Combined mod"
    names = ", ".join(source.label for source in plan.sources)
    info = package_info or ModPackageInfo(title=title, version="1.0", description=f"Combined from: {names}.")
    if plan.layout == LAYOUT_LOOSE:
        data = _verify_unchanged(prepared, stop_event)
        if on_log:
            on_log(f"Writing {len(plan.files)} files from {len(plan.sources)} builds...")
        if root.is_dir():
            root.rmdir()  # An empty folder was chosen; publication needs the name free.
        zip_path = _write_loose(prepared, root, data, package_info=info, create_zip=create_zip, stop_event=stop_event)
        return CombinedMeshBuildResult(root, zip_path, plan.layout, plan.manager_profile, plan.target_paths,
                                       tuple(source.label for source in plan.sources))
    if game is None:
        raise ValueError("Combining these builds into a DMM archive group needs the game folder. Load the game first.")
    from cdmw.core.mod_export_history import file_mod_history
    from cdmw.services.mod_merge_service import export_merged_mod, prepare_mod_merge

    _verify_unchanged(prepared, stop_event)
    merge = prepare_mod_merge([Path(source.folder) for source in plan.sources], game, entries=entries,
                              read_entry=read_entry, on_log=on_log, stop_event=stop_event)
    if merge.conflicts:
        raise ValueError("These builds cannot be combined:\n" + "\n".join(f"- {line}" for line in merge.conflicts))
    result = export_merged_mod(merge, root, title=title, on_log=on_log, stop_event=stop_event)
    package_root = Path(getattr(result, "package_root", root))
    file_mod_history(package_root, {SESSION_METADATA: _combined_metadata(prepared)}, stop_event=stop_event)
    zip_path = None
    if create_zip:
        from cdmw.core.mod_package import _write_package_zip

        zip_path = package_root.with_name(package_root.name + ".zip")
        _write_package_zip(package_root, zip_path=zip_path, stop_event=stop_event)
    return CombinedMeshBuildResult(package_root, zip_path, plan.layout, "dmm", plan.target_paths,
                                   tuple(source.label for source in plan.sources))


__all__ = [
    "COMBINED_METADATA_FORMAT",
    "CombinedMeshBuildResult",
    "PreparedMeshBuildCombine",
    "export_combined_mesh_builds",
    "merge_build_compatibility",
    "prepare_mesh_build_combine",
    "read_mesh_build",
]
