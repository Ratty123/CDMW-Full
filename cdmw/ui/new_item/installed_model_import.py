"""Adapt a witnessed installed PAC to the existing authored-model import path."""
from cdmw.core.owned_temp import cleanup_owned_temp_directory, create_owned_temp_directory
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.dmm_character_models import bind_installed_materials, prepare_installed_character_model
from cdmw.ui.new_item.model_import import load_model_import_source, prepare_model_import_mesh_edit, _preview_texture_fingerprint


def load_installed_model(request, snapshot, *, stop_event=None, on_log=None):
    root = create_owned_temp_directory(prefix="cdmw_installed_character_")
    source = None
    try:
        path, skins, revision, bindings = prepare_installed_character_model(request, snapshot, root, stop_event=stop_event)
        import_path = path
        if skins:
            from cdmw.modding.mesh_glb_interchange import _build_glb
            from cdmw.modding.mesh_parser import parse_pac
            # The authored-skin pipeline consumes GLB joint identities. Serialize
            # the proven PAC/PAB binding through that real interchange format;
            # do not relabel a PAC or relax the target rig's validation.
            mesh = parse_pac(path.read_bytes(), str(path))
            for part, skin in zip(mesh.submeshes, skins, strict=True):
                part.interchange_skin = skin
            import_path = root / path.with_suffix('.glb').name
            raise_if_cancelled(stop_event)
            import_path.write_bytes(_build_glb(mesh))
        raise_if_cancelled(stop_event)
        source = load_model_import_source(import_path, extract_root=root, stop_event=stop_event, on_log=on_log)
        source.chosen_path = path
        bind_installed_materials(source.scene.mesh, root, bindings)
        source.scene, source.preview_model, _, source.texture_count = prepare_model_import_mesh_edit(
            source.scene.mesh, scene=source.scene, model_path=import_path, stop_event=stop_event)
        source.preview_mesh = source.scene.mesh
        source.external_texture_fingerprint = _preview_texture_fingerprint(source.preview_model, stop_event)
        source.owns_extract_root = True
        source.dmm_source_revision = revision
        revision.validate(stop_event)
        return source
    except BaseException:
        if source is not None:
            source.cleanup()
        cleanup_owned_temp_directory(root)
        raise
