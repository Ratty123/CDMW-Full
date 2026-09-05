"""Captured item inputs for cancellable Effects preview preparation."""

from __future__ import annotations

from dataclasses import dataclass

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.new_item_materials import glow_preview_mesh
from cdmw.ui.new_item.model_import import bake_mesh


@dataclass(frozen=True, slots=True)
class PlannedEffectItemSource:
    source: object
    placement: object
    applied: bool
    preview_model: object
    rebuilt_data: bytes
    snapshot: object
    template_key: int | None
    glow: object

    def __call__(self, stop_event):
        self._check_cancelled(stop_event)
        source = self.source
        if source is not None:
            source_origin = None
            origin_reader = getattr(source, "baked_origin", None)
            if callable(origin_reader):
                try:
                    values = tuple(float(value) for value in origin_reader())
                except (TypeError, ValueError):
                    values = ()
                if len(values) == 3:
                    source_origin = values
            for candidate in (source.baked_preview_mesh, source.baked_scene_mesh):
                self._check_cancelled(stop_event)
                try:
                    decoded = candidate()
                    self._check_cancelled(stop_event)
                    baked = bake_mesh(decoded, self.placement, origin=source_origin)
                except RunCancelled:
                    raise
                except Exception:  # noqa: BLE001 - preserve the established source fallback
                    continue
                if baked is not None:
                    placed_origin = (
                        tuple(source_origin[axis] + self.placement.offset[axis] for axis in range(3))
                        if source_origin is not None else None
                    )
                    return self._finish(baked, "applied" if self.applied else "placed", stop_event, placed_origin)

        model = self.preview_model
        if model is not None and getattr(model, "meshes", None):
            from cdmw.services.effect_placement_preview import mesh_names_textures
            from cdmw.services.mesh_rust_preview_cache import parsed_mesh_from_model_preview

            self._check_cancelled(stop_event)
            try:
                mesh = parsed_mesh_from_model_preview(model)
            except RunCancelled:
                raise
            except Exception:  # noqa: BLE001 - retain the bare geometry fallback
                mesh = None
            if mesh is not None and mesh_names_textures(mesh):
                return self._finish(mesh, "applied", stop_event)

        from cdmw.services.mesh_workflow_service import parse_pac
        from cdmw.ui.new_item.item_preview_materials import placement_reference_mesh

        mesh = None
        if self.rebuilt_data:
            self._check_cancelled(stop_event)
            try:
                mesh = parse_pac(self.rebuilt_data, "imported model")
            except RunCancelled:
                raise
            except Exception:  # noqa: BLE001 - a failed parse leaves the existing viewport usable
                pass
        elif self.snapshot is not None:
            for entry in self._template_entries():
                self._check_cancelled(stop_event)
                try:
                    payload = self.snapshot.payload(entry.path)
                    self._check_cancelled(stop_event)
                    parsed = parse_pac(payload, entry.path)
                except RunCancelled:
                    raise
                except Exception:  # noqa: BLE001 - an absent component must not hide the primary
                    continue
                mesh = parsed if mesh is None else placement_reference_mesh(mesh, parsed)
        if mesh is None:
            return None, ""
        return self._finish(mesh, "applied" if self.applied else "template", stop_event)

    def _finish(self, mesh, kind, stop_event, origin=None):
        self._check_cancelled(stop_event)
        preview = glow_preview_mesh(mesh, self.glow)
        if self._is_wearable():
            point = origin
            if point is None and getattr(preview, "bbox_min", None) is not None and getattr(preview, "bbox_max", None) is not None:
                point = tuple((float(preview.bbox_min[axis]) + float(preview.bbox_max[axis])) * 0.5 for axis in range(3))
            if point is not None:
                setattr(preview, "_cdmw_effect_item_origin", point)
        self._check_cancelled(stop_event)
        return preview, kind

    def _template_entries(self):
        if self.snapshot is None or self.template_key is None:
            return ()
        try:
            family = self.snapshot.family(self.template_key)
            entries = tuple(self.snapshot.entry(item.path) for item in family.files_for("pac") if item.exists)
        except Exception:  # noqa: BLE001 - an unresolved template has no preview mesh
            return ()
        if not entries:
            return ()
        stem = str(getattr(family, "model_stem", "")).casefold()
        primary = next((entry for entry in entries if entry.basename.casefold() == f"{stem}.pac"), entries[0])
        return primary, *(entry for entry in entries if entry.path != primary.path)

    def _is_wearable(self):
        if self.snapshot is None or self.template_key is None:
            return False
        from cdmw.domain.new_item.placement import BODY_PLACEMENT_FRAME, equipment_placement_frame

        try:
            row = self.snapshot.row(self.template_key)
            family = self.snapshot.family(self.template_key)
            return equipment_placement_frame(self.snapshot.equip_type_name(row), family.model_folder) == BODY_PLACEMENT_FRAME
        except Exception:  # noqa: BLE001 - unresolved families retain the ordinary item origin
            return False

    @staticmethod
    def _check_cancelled(stop_event):
        if stop_event.is_set():
            raise RunCancelled("Item effect preview cancelled")
