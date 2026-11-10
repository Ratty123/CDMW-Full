"""Package view-only worn pieces without adding them to the editable mesh."""
from __future__ import annotations
import threading


def prepare_item_set_references(session, contexts, stop_event, progress=None):
    # This runs inside MeshRustSessionPrepareWorker, never on the UI thread.
    from cdmw.services import mesh_rust_authoring as authoring
    from cdmw.workers.mesh_archive_refit_worker import prepare_archive_refit_source

    if not contexts:
        return []
    stop_event = stop_event or threading.Event()
    if len(contexts) > 33:
        raise ValueError("A set preview supports at most 32 additional model files.")
    source = session.authoritative_service._session(session.authoritative_session_id)
    selected = contexts[0].selected_entry
    if (str(source.base_mesh.path).casefold() != selected.path.casefold()
            or (selected.prepared_sha256 and selected.prepared_sha256.casefold()
                != authoring._sha256_bytes(source.original_data).casefold())
            or len({context.selected_entry.identity for context in contexts}) != len(contexts)):
        raise ValueError("Item set dependencies do not match the selected mesh")
    rows = []
    for index, context in enumerate(contexts[1:], 1):
        session._raise_if_cancelled(stop_event)
        entry = context.selected_entry
        if progress is not None:
            progress("Preparing reference meshes...")
        prepared = prepare_archive_refit_source(
            {"_archive_entry": entry, "_archive_dependencies": context}, stop_event)
        try:
            mesh = prepared["_archive_snapshot"].mesh
            appearance = prepared.get("_archive_neutral_appearance")
            if appearance is not None:
                mesh = appearance.to_neutral(mesh)
            document = authoring._atomic_write_payload(
                session.root, f"reference-{index:02d}.bin",
                authoring.PreparedMeshDocument(authoring.encode_mesh_document(
                    authoring._mesh_document_arrays(mesh),
                    max_payload_bytes=authoring.RUST_MESH_MAX_PAYLOAD_BYTES)),
                data_type=authoring.BINARY_MESH_DOCUMENT_TYPE,
                element_count=sum(len(level) for level in authoring._mesh_lods(mesh)),
                expected_root_identity=session.root_identity,
            )
            synthesis = authoring._RustMaterialSynthesisState()
            textures = authoring._mesh_texture_payloads(
                session.root, mesh, expected_root_identity=session.root_identity,
                stop_event=stop_event, synthesis_state=synthesis,
            )
            rows.append({
                "index": index, "name": entry.basename, "role": "reference",
                "document": document, "textures": textures,
                "material_presentations": authoring._mesh_material_presentations(
                    mesh, generated_overrides=synthesis.presentation_overrides),
            })
        finally:
            # DDS files are owned copies by now; release the temporary cache lease.
            prepared.clear()
        session._raise_if_cancelled(stop_event)
    return rows
