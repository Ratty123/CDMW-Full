"""Build a Damiane barber-registration test mod without installing it.

Uses the resident archive worker, mounted precedence, existing prefab/pathc
writers, and the shared overlay package exporter. Game selection and save/load
remain acceptance checks; continuing code implementation does not establish them.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication
from cdmw.core.pappt_format import parse_pappt
from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_texture
from cdmw.core.pbd_cloth import parse_pbd_config_materials
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.archives.catalogue import ArchiveLookupKind, ArchiveLookupRequest
from cdmw.domain.archives.catalogue_operations import OpenArchiveRequest, PrepareEntryRequest
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest
from cdmw.domain.hair_registration import HairRegistrationError, read_hair_choices
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
from cdmw.services.hair_registration import (
    DAMIANE_MESH_PARAM, PART_PREFAB_TABLE, prepare_damiane_hair_registration,
)
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient
from tools.dotnet_archive_backend.probe_character_catalog import source_snapshot
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter


def select_active_entry(rows, path):
    exact = [row for row in rows if row.path.replace("\\", "/").casefold() == path.casefold()]
    active = [row for row in exact if row.is_active_override]
    candidates = active or exact
    if len(candidates) != 1:
        raise HairRegistrationError(f"Expected one mounted source for {path}; found {len(candidates)}.")
    if candidates[0].override_state.casefold().startswith("shadowed"):
        raise HairRegistrationError(f"The only supplied source is shadowed: {path}")
    return candidates[0]


def collect_lookup_entries(waiter, request_id):
    result = waiter.wait(request_id)
    parts = (*waiter.batches.pop(request_id, ()), result)
    if any(part.truncated for part in parts):
        raise HairRegistrationError("Archive lookup was truncated.")
    if any(part.session_id != result.session_id for part in parts):
        raise HairRegistrationError("Archive lookup returned a different source session.")
    entries = tuple(entry for part in parts for entry in part.entries)
    if len(entries) != result.total_matches or len({entry.entry_id for entry in entries}) != len(entries):
        raise HairRegistrationError("Archive lookup returned incomplete or duplicate entries.")
    return entries


def run(game_root: Path, output: Path, cache_root: Path, new_stem: str, template_index: int = 0, *, authoring_probe=None):
    game_root, output, cache_root = game_root.resolve(), output.resolve(), cache_root.resolve()
    if output.exists() or output.is_relative_to(game_root) or game_root.is_relative_to(output):
        raise ValueError("Output must be a new directory outside the installed game.")
    if cache_root.is_relative_to(game_root) or cache_root.is_relative_to(output) or output.is_relative_to(cache_root):
        raise ValueError("The worker cache must be outside the game and the output package.")
    app = QCoreApplication.instance() or QCoreApplication([])
    before = source_snapshot(game_root)
    pathc_path = game_root / "meta" / "0.pathc"
    if not pathc_path.is_file() or pathc_path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("A supported texture registry is required for the cloned icon.")
    pathc_bytes = pathc_path.read_bytes()
    client = ArchiveBackendClient(cache_root=cache_root)
    service, stage = ArchiveCatalogueService(client), None
    waiter = _Awaiter(service)
    files, entries, prepared_rows = {}, {}, {}
    try:
        session = waiter.wait(service.open_archive(OpenArchiveRequest(str(game_root)), ui_generation=1), timeout_ms=300_000)
        print(f"Opened {session.entry_count:,} entries; fingerprint {session.fingerprint}", flush=True)

        def lookup(paths, session_id=None):
            request_id = service.resolve_entries(ArchiveLookupRequest(
                session_id or session.session_id, ArchiveLookupKind.EXACT_PATHS, values=tuple(paths)), ui_generation=1)
            return collect_lookup_entries(waiter, request_id)

        def get_file(path):
            key = path.replace("\\", "/").casefold()
            if key in files:
                return files[key]
            row = select_active_entry(lookup((key,)), key)
            if row.original_size > 64 * 1024 * 1024:
                raise HairRegistrationError(f"Dependency exceeds the proof's 64 MiB bound: {path}")
            prepared = waiter.wait(service.prepare_entry(PrepareEntryRequest(session.session_id, row.entry_id), ui_generation=1), timeout_ms=60_000)
            payload = Path(prepared.prepared_path).read_bytes()
            if len(payload) != prepared.size or hashlib.sha256(payload).hexdigest() != prepared.sha256:
                raise HairRegistrationError(f"Prepared source verification failed: {path}")
            entry = service.compatibility_entry(row)
            entry.prepared_path = Path(prepared.prepared_path)
            files[key], entries[key] = payload, entry
            prepared_rows[key] = {"entry": asdict(row), "sha256": prepared.sha256, "size": prepared.size}
            return payload

        choices = read_hair_choices(get_file(DAMIANE_MESH_PARAM))
        if not 0 <= template_index < len(choices):
            raise HairRegistrationError("The requested template choice does not exist.")
        donor = choices[template_index]
        record = parse_pappt(get_file(PART_PREFAB_TABLE)).find(donor.prefab_stem)
        if record is None:
            raise HairRegistrationError("The hair template has no prefab-table registration.")
        prefab = get_file(record.prefab_path)
        mesh_refs = tuple(item.text for item in decode_prefab_binary(prefab).resource_strings())
        if len(mesh_refs) != 1:
            raise HairRegistrationError("The hair template must name one mesh.")
        mesh_path = mesh_refs[0].casefold()
        mesh_bytes = get_file(mesh_path)
        material_path = mesh_path.replace("character/model/", "character/modelproperty/", 1) + "_xml"
        material_bytes = get_file(material_path)
        physics_path = mesh_path.replace("character/model/", "character/bin__/meshphysics/", 1)[:-4] + ".hkx"
        get_file(physics_path)
        get_file(donor.icon_path)
        material_root = ET.fromstring("<Root>" + material_bytes.decode("utf-8-sig") + "</Root>")
        texture_paths = sorted({node.get("_path") for node in material_root.iter()
                                if node.get("_path", "").lower().endswith(".dds")})
        for path in texture_paths:
            get_file(path)
        pbd_config = parse_pbd_config_materials(get_file("character/descriptors/pbd/pbdconfig.xml").decode("utf-8-sig"))
        pbd_names = {node.get("_pbdSimulationMaterialName") for node in material_root.iter()
                     if node.get("_pbdSimulationMaterialName")}
        if pbd_names != {"Hair"} or "hair" not in pbd_config:
            raise HairRegistrationError("The template does not use the proven Hair simulation profile.")
        pbd = pbd_config["hair"]
        get_file("character/descriptors/pbd/" + pbd.filename.replace("\\", "/"))
        model = parse_mesh(mesh_bytes, mesh_path)
        if not model.submeshes:
            raise HairRegistrationError("The donor hair has no readable geometry.")
        if authoring_probe is not None:
            result = authoring_probe(files, entries, get_file, model, game_root, output, new_stem)
            if before != source_snapshot(game_root) or pathc_bytes != pathc_path.read_bytes():
                raise HairRegistrationError("Installed source files changed during authoring proof.")
            return result
        plan = prepare_damiane_hair_registration(files, new_stem=new_stem, existing_paths=tuple(files), template_index=template_index)
        conflicts = lookup(item.path for item in plan.additions)
        if conflicts:
            raise HairRegistrationError("New asset paths already exist: " + ", ".join(row.path for row in conflicts))
        plan.check_sources(files)
        registry = parse_pathc(pathc_bytes)
        if encode_pathc(registry) != pathc_bytes:
            raise HairRegistrationError("The current texture registry does not round-trip exactly.")
        icon = next(item for item in plan.additions if item.path.endswith(".dds"))
        # The selection XML uses mixed case; PATHC hashes canonical archive paths.
        registered = register_texture(registry, icon.path, like=donor.icon_path.casefold(), dds_header=icon.data)
        new_pathc = encode_pathc(registered)
        if parse_pathc(new_pathc) != registered or len(registered.entries) != len(registry.entries) + 1:
            raise HairRegistrationError("The cloned icon was not registered exactly once.")
        patches = tuple(ArchivePatchRequest(entries[item.path], item.data) for item in plan.replacements)
        additions = tuple(ArchiveAddRequest.from_template(
            entries[donor.icon_path.casefold() if item.path.endswith(".dds") else item.path.replace(new_stem, donor.prefab_stem)],
            item.path, item.data) for item in plan.additions)
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
        shared = export_archive_overlay_package(patches, additions, package_root=stage, game_root=game_root,
                                                metadata_files=(("meta/0.pathc", new_pathc),), on_log=print)
        title = "Damiane - Additional Hair Choice Compatibility Test"
        description = (f"Adds barber choice {plan.choice_index + 1}, cloned from Damiane's hairstyle {template_index + 1}. "
                       "Runtime selection and save/load are unverified.")
        manifest = {"format": "v1", "schema_version": 1, "kind": "archive_override_mod", "name": title,
                    "title": title, "game": "Crimson Desert", "target_game": shared.target_game, "version": "0.0.1",
                    "description": description, "files_dir": ".", "manager_targets": ["dmm"],
                    "manager_target_labels": ["Definitive Mod Manager"], "structure": "archive_group",
                    "archive_group": shared.group, "file_count": shared.file_count, "overrides": list(shared.paths)}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (stage / "modinfo.json").write_text(json.dumps({"name": title, "version": "0.0.1", "description": description}, indent=2), encoding="utf-8")
        # Reopen the actual built archive through the same worker, not just the
        # in-memory plan, and compare every decoded payload before publication.
        package_session = waiter.wait(service.open_archive(OpenArchiveRequest(str(stage)), ui_generation=2), timeout_ms=120_000)
        wanted = {item.path: item.data for item in (*plan.replacements, *plan.additions)}
        packaged = lookup(wanted, package_session.session_id)
        if len(packaged) != len(wanted):
            raise HairRegistrationError("The built archive does not contain every planned file.")
        for row in packaged:
            result = waiter.wait(service.prepare_entry(PrepareEntryRequest(package_session.session_id, row.entry_id), ui_generation=2), timeout_ms=60_000)
            if Path(result.prepared_path).read_bytes() != wanted[row.path]:
                raise HairRegistrationError(f"Packaged payload failed round-trip: {row.path}")
        if before != source_snapshot(game_root) or pathc_bytes != pathc_path.read_bytes():
            raise HairRegistrationError("Installed source files changed during preparation.")
        evidence = {"schema": "cdmw_hair_registration_proof_v1", "created_utc": datetime.now(timezone.utc).isoformat(),
                    "runtime_verified": False, "game_root": str(game_root), "fingerprint": session.fingerprint,
                    "original_choice_count": len(choices), "new_choice_index": plan.choice_index, "new_stem": new_stem,
                    "source_unchanged": True, "package_roundtrip_files": len(packaged),
                    "mesh_vertices": sum(len(part.vertices) for part in model.submeshes),
                    "mesh_triangles": sum(len(part.faces) for part in model.submeshes),
                    "physics_profile": asdict(pbd), "material_textures": texture_paths,
                    "sources": prepared_rows, "original_pathc_sha256": hashlib.sha256(pathc_bytes).hexdigest(),
                    "output_sha256": {str(path.relative_to(stage)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in stage.rglob("*") if path.is_file()}}
        (stage / "compatibility-proof.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        (stage / "README.txt").write_text(
            f"{title}\n\nThis is a compatibility test, not the hair editor.\n"
            f"Original choices: {len(choices)}. Expected choices after mounting: {len(choices)+1}.\n"
            f"The final tile (index {plan.choice_index}) deliberately looks like the template at index {template_index}.\n\n"
            "1. Import this package through the existing mod manager and enable/mount it.\n"
            "2. Use a separate test save with Damiane and visit a barber.\n"
            "3. Check that the original choices remain and one additional final tile appears.\n"
            "4. Choose the final tile and check that the hair has its textures and normal movement.\n"
            "5. Save, reload, revisit the barber, and verify the final tile remains selected.\n"
            "6. Select an original hairstyle before disabling the test mod through the manager.\n\n"
            "Do not combine this test with another mod that replaces the same prefab table, hair-option XML or texture registry.\n"
            "The package has not been installed or tested in the game by this probe.\n",
            encoding="utf-8")
        os.rename(stage, output)
        print(f"Prepared {output}; {len(packaged)} files round-trip; game verification still required.", flush=True)
        return evidence
    finally:
        client.shutdown()
        _Awaiter._wait_until(lambda: client.process_id == 0, timeout_ms=10_000)
        app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--new-stem", default="cd_phw_00_hair_00_9000_01_player")
    parser.add_argument("--template-index", type=int, default=0)
    args = parser.parse_args()
    run(args.package_root, args.output, args.cache_root, args.new_stem, args.template_index)
