"""Read-only Hair workflow evidence through resident queries and production loaders.

Requires explicitly authorized installed game inputs. All output stays in the
named temporary evidence directory. This is offscreen workflow evidence, not a
normal-window interaction or in-game acceptance check.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import json
import os
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.domain.archives.catalogue_operations import OpenArchiveRequest
from cdmw.domain.archives.character_catalogue import CharacterCatalogSearchRequest, CharacterCatalogDetailRequest
from cdmw.domain.hair_registration import read_hair_choices
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.hair_registration import DAMIANE_MESH_PARAM
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
from cdmw.ui.mesh_editor.hair_context_preparation import HairContextPreparation
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient
from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter
from tools.dotnet_archive_backend.probe_character_catalog import source_snapshot


def run(args):
    app = QApplication.instance() or QApplication([])
    args.evidence.mkdir(parents=True, exist_ok=True)
    before = source_snapshot(args.game)
    client = ArchiveBackendClient(cache_root=args.cache, worker_executable=args.worker)
    service = ArchiveCatalogueService(client)
    waiter = _Awaiter(service)
    results = {}
    try:
        session = waiter.wait(service.open_archive(OpenArchiveRequest(str(args.game)), ui_generation=1), timeout_ms=600_000)
        waiter.wait(service.build_character_catalog(session.session_id, ui_generation=1), timeout_ms=600_000)
        for role in ("head", "body"):
            rows = waiter.wait(service.search_character_catalog(CharacterCatalogSearchRequest(session.session_id,
                tab="all", selection_purpose="hair_" + role), ui_generation=2), timeout_ms=60_000)
            if not rows.rows:
                diagnostic = waiter.wait(service.search_character_catalog(CharacterCatalogSearchRequest(session.session_id, tab="all", query="cd_phw_00_head_00_0111" if role=="head" else "cd_phw_00_nude_00_0001_damian"), ui_generation=2))
                raise RuntimeError("No eligible " + role + ": " + json.dumps([asdict(r) for r in diagnostic.rows]))
            assert all(r.role in ({"head"} if role=="head" else {"body", "whole_character"}) and r.body_family == "2_phw" for r in rows.rows)
            results[role + "_candidates"] = rows.total_matches
        contexts, failures = [], []
        resolver = HairContextPreparation(service)
        resolver.ready.connect(contexts.append)
        resolver.failed.connect(failures.append)
        started = time.perf_counter()
        resolver.start()
        assert waiter._wait_until(lambda: contexts or failures, timeout_ms=300_000), "Character context timeout"
        if failures:
            raise RuntimeError(failures[0])
        context = contexts[-1]
        results["character_preparation_ms"] = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        resolver.start()
        assert contexts[-1] is context
        results["cached_context_ms"] = (time.perf_counter() - started) * 1000
        results["head"] = context.head.path
        results["body"] = context.body.path
        entry = context.dependencies.entry_for_path(DAMIANE_MESH_PARAM)
        if entry is None:
            raise RuntimeError("Automatic context omitted the barber descriptor")
        choices = read_hair_choices(read_archive_entry_data(entry)[0])
        path = "character/model/1_pc/2_phw/head/hair/" + choices[0].prefab_stem + ".pac"
        detail = waiter.wait(service.get_character_catalog_detail(CharacterCatalogDetailRequest(session.session_id, "asset:" + path), ui_generation=3))
        prepared = []
        preparer = CharacterPreviewPreparation(service)
        preparer.ready.connect(lambda _token, inputs: prepared.append(inputs))
        preparer.failed.connect(lambda _token, message: failures.append(message))
        preparer.start(detail, 3)
        assert waiter._wait_until(lambda: prepared or failures, timeout_ms=300_000), "Hairstyle dependency timeout"
        if failures:
            raise RuntimeError(failures[0])
        inputs = prepared[0]
        assert inputs.dependencies_complete
        target = inputs.entries_by_id[detail.models[0].entry_id]
        paths, names = {}, {}
        for item in inputs.entries:
            paths.setdefault(item.path.casefold(), []).append(item)
            names.setdefault(item.basename.casefold(), []).append(item)
        dependencies = ArchiveWorkflowDependencyContext(target, inputs.entries, paths, names, True)
        results["target"] = target.path
        print(json.dumps(results), flush=True)
        # Execute exactly the reference/material loader used by the protocol
        # worker, on a background thread while Qt continues processing events.
        def prepare_editor():
            from cdmw.workers.mesh_archive_refit_worker import prepare_archive_refit_source, prepare_hair_reference_source
            from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, _mesh_document_payload
            from cdmw.services.mesh_rust_hair import setup_hair
            from cdmw.services.mesh_service import MeshService
            stop = threading.Event()
            leases = []
            candidate = json.loads(args.candidate.read_text(encoding="utf-8")) if args.candidate else None
            authority = authoring = None
            try:
                started = time.perf_counter()
                target_args = prepare_archive_refit_source({"_archive_entry": target, "_archive_dependencies": dependencies}, stop)
                leases.append(target_args["_archive_preview_lease"])
                results["donor_loading_ms"]=(time.perf_counter()-started)*1000
                snapshot = target_args["_archive_snapshot"]
                authority = MeshService()
                setattr(snapshot.mesh, "_cdmw_original_data", snapshot.original_data)
                view = authority.open_edit_session(snapshot.mesh, session_id="hair-workflow-probe", mode="edit")
                controller = SimpleNamespace(mesh_service=authority, active_session_id=view.session_id)
                stamp=time.perf_counter()
                authoring = RustMeshAuthoringSession.create(controller, args.evidence / "session", process_generation=1)
                results["authoring_session_ms"]=(time.perf_counter()-stamp)*1000
                command = context.arguments()
                command.update(mode=args.mode, _target_entry=target, _target_dependencies=dependencies)
                if candidate:
                    command["target_stem"] = candidate["hair"]["template"]["target_stem"]
                stamp=time.perf_counter()
                command = prepare_hair_reference_source(command, stop)
                results["head_loading_ms"]=(time.perf_counter()-stamp)*1000
                leases.append(command["_archive_preview_lease"])
                stamp=time.perf_counter()
                body = prepare_hair_reference_source({"_archive_entry": context.body, "_archive_dependencies": context.dependencies, "_hair_context_identity": command["_hair_context_identity"]}, stop)
                results["body_loading_ms"]=(time.perf_counter()-stamp)*1000
                leases.append(body["_archive_preview_lease"])
                command.update(_body_snapshot=body["_archive_snapshot"], _body_neutral_appearance=body["_archive_neutral_appearance"])
                stamp=time.perf_counter()
                setup_hair(authoring, command, stop)
                results["hair_setup_ms"]=(time.perf_counter()-stamp)*1000
                state = authoring.shadow_service._session(authoring.shadow_session_id)
                stamp=time.perf_counter()
                host = authoring.state_payload(include_document=True)
                results["state_payload_ms"]=(time.perf_counter()-stamp)*1000
                results["editor_preparation_ms"] = (time.perf_counter() - started) * 1000
                # Material factors and DDS are those captured by the real loader.
                output = {"hair": state.hair_state.payload, "document": _mesh_document_payload(state.working_mesh),
                          "host": host, "session_root": str(authoring.root)}
                (args.evidence / "input.json").write_text(json.dumps(output), encoding="utf-8")
                if candidate:
                    import copy
                    import cProfile
                    import pstats
                    from cdmw.services.mesh_rust_hair import apply_hair_candidate
                    from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
                    from cdmw.modding.mesh_parser import parse_mesh
                    from cdmw.services.mesh_hair_output import export_hair_package
                    started=time.perf_counter()
                    apply_hair_candidate(authoring,candidate,"Real Hair workflow")
                    results["first_candidate_ms"]=(time.perf_counter()-started)*1000
                    # Isolate incremental host validation/history with a name
                    # change. This timing is not pointer-to-visible grooming.
                    changed=copy.deepcopy(candidate)
                    changed["hair"]["revision"]+=1
                    changed["hair"]["style_name"]="Workflow timing"
                    reuse=["groups","locks","guides","bindings","vertex_sources","prepared_parts"]
                    changed["hair_update"]={"version":2,"reference":changed["hair"]["scalp"]["identity"],"parts":[],"vertex_updates":[],"reuse":reuse,"base_hair_revision":candidate["hair"]["revision"]}
                    changed["submeshes"]=[]
                    for field in ("scalp","references","collisions",*reuse):changed["hair"].pop(field,None)
                    profile=cProfile.Profile()
                    if args.profile_host:profile.enable()
                    started=time.perf_counter();apply_hair_candidate(authoring,changed,"Incremental timing")
                    results["profiled_incremental_metadata_ms" if args.profile_host else "incremental_metadata_ms"]=(time.perf_counter()-started)*1000
                    if args.profile_host:
                        profile.disable();profile.dump_stats(args.evidence/"host-profile.pstats")
                        with (args.evidence/"host-profile.txt").open("w",encoding="utf-8") as out:pstats.Stats(profile,stream=out).strip_dirs().sort_stats("cumulative").print_stats(20)
                    service=authoring.shadow_service;current=service._session(authoring.shadow_session_id)
                    current.mesh_layer_project_path=args.evidence/"draft/project.json"
                    service.retry_mesh_layer_autosave(authoring.shadow_session_id)
                    draft=copy.deepcopy(current.base_mesh)
                    loaded=load_mesh_layer_project(draft,current.mesh_layer_project_path,expected_source_asset_sha256=current.mesh_asset_source_hash)
                    assert loaded["hair_state"]==current.hair_state and loaded["replacement_state"]==current.replacement_state
                    results["draft_reopened"]=True
                    snapshot=service.capture_export_snapshot(authoring.shadow_session_id)
                    rebuilt=service._replacement_output_for_snapshot(snapshot)
                    parsed=parse_mesh(rebuilt.data,target.path)
                    results["reparsed_vertices"]=sum(len(part.vertices) for part in parsed.submeshes)
                    if not args.skip_package:
                        export_hair_package(snapshot,rebuilt,target,args.evidence/"package",on_log=print)
                        results["package_reparsed"]=True
            except Exception as error:
                import traceback
                failures.append(traceback.format_exc())
            finally:
                for lease in leases:
                    if lease is not None and lease.lease is not None:
                        lease.lease.release()
                if authoring is not None:
                    # Keep immutable material files for the renderer probe.
                    authoring.closed = True
                if authority is not None:
                    authority.close_edit_session("hair-workflow-probe", force_without_saving=True)
        thread = threading.Thread(target=prepare_editor)
        thread.start()
        assert waiter._wait_until(lambda: not thread.is_alive(), timeout_ms=600_000), "Editor preparation timeout"
        thread.join()
        if failures:
            raise RuntimeError(failures[0])
        assert source_snapshot(args.game) == before, "Installed archives changed"
        results["archives_unchanged"] = True
        (args.evidence / "workflow.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results), flush=True)
    finally:
        client.shutdown()
        waiter._wait_until(lambda: client._process is None, timeout_ms=10_000)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "cache", "worker", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--skip-package", action="store_true")
    parser.add_argument("--profile-host", action="store_true")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--mode", choices=("generated", "existing"), default="generated")
    run(parser.parse_args())
