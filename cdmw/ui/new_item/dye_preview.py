"""Worker-owned dye preview from the same material transformation used by export."""
from dataclasses import replace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.services.new_item_dyes import load_dye_index, prepare_dye_assignments, dye_mask_revision, read_dye_mask
from cdmw.services.new_item_variants import xml_path, variant_family
from cdmw.ui.new_item.item_preview import ProgressivePreviewSource


def variant_dye_preview_source(controller):
    identity = controller.current_variant_identity()
    if identity is None or controller.snapshot is None:
        raise ValueError("Select a model variant first.")
    controller._sync_variant_state()
    state = controller._variant_states.get(identity)
    if state is None:
        raise ValueError("Customize this variant's dye assignments first.")
    choice = state.appearance
    snapshot = controller.snapshot
    result, source, scene = (state.result,state.source,state.scene) if choice.custom_model else (None,None,None)
    if choice.custom_model and result is None:
        raise ValueError("Apply this variant's model before previewing its dye material.")
    template_key = controller.draft.template_key
    target = snapshot.entry(choice.model_path)
    material_path = xml_path(choice.model_path)
    mask_revisions = tuple((value.mask_path, dye_mask_revision(value.mask_path))
                           for value in choice.dyes or () if value.mask_path)
    token = ("variant-dye",identity,choice,id(result),mask_revisions)

    def model_files():
        from cdmw.services.new_item_planning import ModelFiles, model_files_from_import
        from cdmw.services.new_item_materials import route_model_files
        if result is None:
            return ModelFiles(snapshot.payload(choice.model_path),{material_path:snapshot.payload(material_path)})
        if isinstance(result,ModelFiles):
            return result
        files = model_files_from_import(result,family=variant_family(snapshot.family(template_key),choice))
        return route_model_files(files,MaterialRoute(choice.material_route),result=result,scene=scene,glow=choice.glow_choice())

    def geometry(stop_event):
        from cdmw.modding.mesh_parser import parse_pac
        raise_if_cancelled(stop_event)
        payload = bytes(getattr(result,"rebuilt_data",b"") or getattr(result,"pac_data",b"")) if result is not None else snapshot.payload(choice.model_path)
        return parse_pac(payload,choice.model_path)

    def materials(stop_event,**context):
        from cdmw.core.partprefab_dye_table import encode_prefab_dye_row
        from cdmw.core.structured_binary_editor import replace_table_row
        from cdmw.ui.new_item.template_preview_cache import build_native_template_preview
        raise_if_cancelled(stop_event)
        if context.get("output_root") is None or context.get("native_preview_core_cache_root") is None:
            raise ValueError("Dye-material preview requires the resident Preview Core.")
        files = model_files()
        index = load_dye_index(snapshot,stop_event=stop_event)
        row = index.rows.get(choice.model_path.casefold())
        if row is None:
            raise ValueError("This variant has no decoded dye preset.")
        payloads = dict(files.side_files)
        payloads[choice.model_path] = files.pac_data
        masks = {}
        for ordinal,assignment in enumerate(choice.dyes or ()):
            raise_if_cancelled(stop_event)
            if assignment.mask_path:
                data = read_dye_mask(snapshot, assignment.mask_path,
                                     expected_revision=dict(mask_revisions)[assignment.mask_path])
                path = f"character/texture/__cdmw_dye_preview_{hashlib.sha256(data).hexdigest()[:16]}_{ordinal}.dds"
                payloads[path] = data
                masks[assignment.target_submesh] = path
        parts,material = prepare_dye_assignments(row,payloads.get(material_path,snapshot.payload(material_path)),
            snapshot.payload(material_path),choice.dyes,imported=choice.custom_model,mask_paths=masks)
        payloads[material_path] = material
        body,header = replace_table_row(index.pair.payload,index.pair.header,row.key,encode_prefab_dye_row(replace(row,submeshes=parts)))
        payloads[index.pair.payload_entry.path],payloads[index.pair.header_entry.path] = body,header
        with TemporaryDirectory(prefix="cdmw-dye-preview-") as directory:
            prepared = []
            for ordinal,(path,data) in enumerate(payloads.items()):
                raise_if_cancelled(stop_event)
                local = Path(directory)/f"{ordinal}{Path(path).suffix}"
                local.write_bytes(data)
                entry = snapshot.entry(path) if snapshot.has_entry(path) else target
                prepared.append(replace(entry,path=path,orig_size=len(data),prepared_path=local,prepared_size=len(data),
                                        prepared_sha256=hashlib.sha256(data).hexdigest(),prepared_note="New Item dye preview"))
            primary = next(value for value in prepared if value.path==choice.model_path)
            prefab = snapshot.entry(choice.prefab_path)
            package = build_native_template_preview(primary,tuple(prepared)+(prefab,), (prefab,),(),template_key,snapshot,stop_event,
                output_root=context["output_root"],native_preview_core_cache_root=context["native_preview_core_cache_root"],
                render_settings=context.get("render_settings"),cache_mode="off",fast_package_ready=context.get("fast_package_ready"))
            if package is None:
                raise ValueError("The authored dye material could not be rendered; the existing viewport remains available.")
            return package
    return token,ProgressivePreviewSource(geometry,materials,source.acquire_usage if source is not None else None,
                                         supports_fast_material_package=True)
