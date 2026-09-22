"""Worker-owned dye preview from the same material transformation used by export."""
from dataclasses import replace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.services.new_item_dyes import load_dye_index, prepare_dye_assignments, prepare_dye_preview_table, dye_mask_revision, read_dye_mask
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

    def model_files(stop_event):
        from cdmw.services.new_item_planning import ModelFiles, model_files_from_import
        from cdmw.services.new_item_materials import route_model_files
        from cdmw.services.new_item_shader_controls import apply_shader_controls
        if result is None:
            if choice.glow_parts or choice.translucency is not None or choice.shader_controls or choice.template_transform:
                from cdmw.services.new_item_template_model import prepare_template_model
                return prepare_template_model(snapshot, [choice.model_path], glow=choice.glow_choice(),
                    translucency=choice.translucency, shader_controls=choice.shader_controls,
                    transform=choice.template_transform, stop_event=stop_event)
            return ModelFiles(snapshot.payload(choice.model_path),{material_path:snapshot.payload(material_path)})
        if isinstance(result,ModelFiles):
            from cdmw.services.new_item_translucency import apply_prebuilt_translucency
            files = apply_prebuilt_translucency(result,MaterialRoute(choice.material_route),choice.translucency,stop_event=stop_event)
            return apply_shader_controls(files, choice.shader_controls)
        files = model_files_from_import(result,family=variant_family(snapshot.family(template_key),choice))
        files = route_model_files(files,MaterialRoute(choice.material_route),result=result,scene=scene,
                                 glow=choice.glow_choice(),translucency=choice.translucency,stop_event=stop_event)
        return apply_shader_controls(files, choice.shader_controls, result=result, scene=scene)

    def geometry(stop_event):
        from cdmw.services.mesh_workflow_service import parse_pac
        raise_if_cancelled(stop_event)
        payload = bytes(getattr(result,"rebuilt_data",b"") or getattr(result,"pac_data",b"")) if result is not None else snapshot.payload(choice.model_path)
        return parse_pac(payload,choice.model_path)

    def materials(stop_event,**context):
        from cdmw.ui.new_item.template_preview_cache import build_native_template_preview
        raise_if_cancelled(stop_event)
        if context.get("output_root") is None or context.get("native_preview_core_cache_root") is None:
            raise ValueError("Dye-material preview requires the resident Preview Core.")
        files = model_files(stop_event)
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
            snapshot.payload(material_path),choice.dyes,imported=choice.custom_model,mask_paths=masks,
            preserve_materials=bool(choice.glow_parts or choice.translucency is not None or choice.shader_controls))
        payloads[material_path] = material
        body,header = prepare_dye_preview_table(index,row,parts)
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
            consume = None
            if choice.shader_controls:
                from types import SimpleNamespace
                from cdmw.services.new_item_shader_controls import shader_control_bindings
                from cdmw.services.shader_controls_preview import shader_preview_mesh
                from cdmw.services.mesh_dotnet_reference_composite import decode_dotnet_native_preview_package
                from cdmw.ui.new_item.item_preview import build_item_preview_package

                mapped = shader_control_bindings(files, choice.shader_controls, result=result, scene=scene)
                settings = tuple(pair for bindings in mapped.values() for pair in bindings)
                authored = SimpleNamespace(
                    has_entry=lambda path: path in payloads or snapshot.has_entry(path),
                    payload=lambda path: payloads[path] if path in payloads else snapshot.payload(path),
                )
                def consume(package):
                    mesh = decode_dotnet_native_preview_package(package, cancelled=stop_event.is_set)
                    mesh = shader_preview_mesh(mesh, settings, snapshot=authored, stop_event=stop_event)
                    return build_item_preview_package(mesh, token=token, output_root=context["output_root"],
                        stop_event=stop_event, include_material_resources=True,
                        render_settings=context.get("render_settings"), cache_mode="off",
                        fast_package_ready=context.get("fast_package_ready"))
            package = build_native_template_preview(primary,tuple(prepared)+(prefab,), (prefab,),(),template_key,snapshot,stop_event,
                output_root=context["output_root"],native_preview_core_cache_root=context["native_preview_core_cache_root"],
                render_settings=context.get("render_settings"),cache_mode="off",fast_package_ready=context.get("fast_package_ready"),
                **({"consume_native_package": consume} if consume is not None else {}))
            if package is None:
                raise ValueError("The authored dye material could not be rendered; the existing viewport remains available.")
            return package
    return token,ProgressivePreviewSource(geometry,materials,source.acquire_usage if source is not None else None,
                                         supports_fast_material_package=True)
