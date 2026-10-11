"""Portable fitting recipes and transactional loaded-outfit application."""

from __future__ import annotations

from dataclasses import dataclass, replace
import io
from pathlib import Path
import re
from typing import Mapping
from uuid import uuid4

from cdmw.core.streaming_json import write_json
from cdmw.core.atomic_file import atomic_binary_writer, atomic_text_writer
from cdmw.services.mesh_morph_file_data import capture_profile_json, write_profile_file, profile_file_text
from cdmw.domain.mesh import (
    MeshMorphFittingRecipe,
    MeshMorphValuePreset,
    MeshRefitDriverRegion,
    MeshRefitGarmentSettings,
    mesh_morph_base_fingerprint,
    mesh_morph_role_topology_fingerprint,
    validate_mesh_morph_fitting_recipe,
    validate_morph_definition_geometry,
    with_morph_garment_corrections,
)
from cdmw.domain.mesh.morph_layers import mesh_morph_profile_definition_fingerprint
from cdmw.services.mesh_morph_profiles import (
    mesh_morph_preset_from_payload,
    mesh_morph_preset_payload,
    mesh_morph_profile_from_payload,
    mesh_morph_profile_payload,
    save_mesh_morph_preset,
    save_mesh_morph_profile,
    mesh_morph_preset_file_data,
    mesh_morph_profile_file_data,
    _streamed_profile_payload,
    _read_object,
    _read_object_stream,
)
from cdmw.services.mesh_service_history import (
    _validated_mesh_morph_profile_files,
)
from cdmw.services.mesh_service_morph_authoring import _merge_edit_results, _refit_settings_batch_payload, _strict_indices


_RECIPE_FORMAT = "cdmw.mesh_refit_recipe.v2"


def _objects(value: object, label: str):
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"Fitting recipe {label} must be an array of objects.")
    return tuple(value)


def fitting_recipe_payload(recipe: MeshMorphFittingRecipe, *, streaming: bool = False) -> dict[str, object]:
    return {
        "format": _RECIPE_FORMAT,
        "recipe_id": recipe.recipe_id,
        "name": recipe.name,
        "profile": (_streamed_profile_payload if streaming else mesh_morph_profile_payload)(recipe.profile),
        "preset": mesh_morph_preset_payload(recipe.preset),
        "driver_submesh_indices": list(recipe.driver_submesh_indices),
        "topology_fingerprint": recipe.topology_fingerprint,
        "base_geometry_fingerprint": recipe.base_geometry_fingerprint,
        "garment_settings": [
            {
                "submesh_index": item.submesh_index,
                "enabled": item.enabled,
                "intensity_percent": item.intensity_percent,
                "mode": item.mode,
                "clearance_percent": item.clearance_percent,
                "tightness_percent": item.tightness_percent,
                "vertex_mask": None if item.vertex_mask is None else [
                    {"vertex_index": index, "weight": weight} for index, weight in item.vertex_mask
                ],
            }
            for item in recipe.garment_settings
        ],
        "garment_regions": [
            {
                "garment_submesh_index": garment,
                "driver_regions": [
                    {"submesh_index": region.submesh_index, "vertex_indices": list(region.vertex_indices)}
                    for region in regions
                ],
            }
            for garment, regions in recipe.garment_regions
        ],
    }


def fitting_recipe_from_payload(payload: Mapping[str, object]) -> MeshMorphFittingRecipe:
    if not isinstance(payload, Mapping) or payload.get("format") not in {_RECIPE_FORMAT, "cdmw.mesh_refit_recipe.v1"}:
        raise ValueError("Unsupported fitting recipe format.")
    profile = payload.get("profile")
    preset = payload.get("preset")
    if not isinstance(profile, Mapping) or not isinstance(preset, Mapping):
        raise ValueError("Fitting recipe must embed its profile and slider preset.")
    settings = []
    for item in _objects(payload.get("garment_settings"), "garment settings"):
        raw_mask = item.get("vertex_mask")
        mask = None if raw_mask is None else tuple(
            (row.get("vertex_index"), float(row.get("weight")))
            for row in _objects(raw_mask, "vertex mask")
        )
        raw_enabled = item.get("enabled", True)
        if payload["format"] == _RECIPE_FORMAT and (
            isinstance(item.get("tightness_percent"), bool)
            or not isinstance(item.get("tightness_percent"), (int, float))
        ):
            raise ValueError("Fitting recipe v2 requires numeric garment tightness.")
        if not isinstance(raw_enabled, bool):
            raise ValueError("Fitting recipe garment enabled flags must be boolean.")
        settings.append(MeshRefitGarmentSettings(
            submesh_index=_strict_indices((item.get("submesh_index"),), label="Recipe garment")[0],
            enabled=raw_enabled,
            intensity_percent=float(item.get("intensity_percent", 100.0)),
            mode=str(item.get("mode") or "surface"),
            clearance_percent=float(item.get("clearance_percent", 0.0)),
            tightness_percent=float(item["tightness_percent"]) if payload["format"] == _RECIPE_FORMAT else 0.0,
            vertex_mask=mask,
        ))
    garment_regions = tuple(
        (
            _strict_indices((item.get("garment_submesh_index"),), label="Recipe region garment")[0],
            tuple(
                MeshRefitDriverRegion(
                    submesh_index=region.get("submesh_index"),
                    vertex_indices=tuple(region.get("vertex_indices") or ()),
                )
                for region in _objects(item.get("driver_regions"), "driver regions")
            ),
        )
        for item in _objects(payload.get("garment_regions", []), "garment regions")
    )
    return MeshMorphFittingRecipe(
        recipe_id=str(payload.get("recipe_id") or ""),
        name=str(payload.get("name") or ""),
        profile=mesh_morph_profile_from_payload(profile),
        preset=mesh_morph_preset_from_payload(preset),
        driver_submesh_indices=_strict_indices(payload.get("driver_submesh_indices"), label="Recipe driver"),
        garment_settings=tuple(settings),
        garment_regions=garment_regions,
        topology_fingerprint=str(payload.get("topology_fingerprint") or ""),
        base_geometry_fingerprint=str(payload.get("base_geometry_fingerprint") or ""),
    )


def read_fitting_recipe(path: str | Path, *, max_bytes: int | None = None) -> MeshMorphFittingRecipe:
    source = Path(path).expanduser()
    if max_bytes is not None and source.stat().st_size > max_bytes:
        raise ValueError("Fitting recipe exceeds its configured file limit.")
    return fitting_recipe_from_payload(_read_object(source, parse_definitions=True))


def serialized_fitting_recipe(recipe: MeshMorphFittingRecipe, *, max_bytes: int | None = None) -> str:
    stream = io.StringIO()
    write_json(stream, fitting_recipe_payload(recipe, streaming=True), max_bytes=max_bytes)
    return stream.getvalue()


@dataclass(slots=True)
class _RefitSetupCache:
    revision: int
    tree_fingerprint: str
    driver_roles: tuple[int, ...]
    recipes: tuple[MeshMorphFittingRecipe, ...]
    neutral_identities: tuple[tuple[tuple[int, ...], str, str], ...]
    matches: tuple[tuple[str, str], ...]
    diagnostics: tuple[str, ...] = ()


def _saved_setup_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"setup-[0-9a-f]{32}", value) is None:
        raise ValueError("Choose a saved fitting setup from the matching list.")
    return value


def _recipe_roles(recipe: MeshMorphFittingRecipe) -> tuple[int, ...]:
    return tuple(sorted(set(recipe.driver_submesh_indices).union(
        item.submesh_index for item in recipe.garment_settings
    )))


def _saved_setup_records(files) -> tuple[tuple[MeshMorphFittingRecipe, ...], tuple[str, ...]]:
    recipes = []
    diagnostics = []
    for relative, encoded in files:
        if "/" in relative or not relative.endswith(".json"):
            continue
        identifier = relative[:-5]
        try:
            _saved_setup_id(identifier)
            with profile_file_text(encoded) as stream:
                recipe = fitting_recipe_from_payload(_read_object_stream(stream, parse_definitions=True))
            if recipe.recipe_id != identifier:
                raise ValueError("The setup file and its stored identity disagree.")
        except (UnicodeError, TypeError, ValueError, OverflowError) as exc:
            diagnostics.append(f"Skipped invalid fitting setup {relative}: {exc}")
            continue
        recipes.append(recipe)
    return tuple(recipes), tuple(diagnostics)


class MeshMorphRecipeMixin:
    """Apply recipes to matching loaded role slots without changing output assets."""

    def _build_refit_recipe_locked(self, session, name, *, recipe_id=None):
        recipe_name = str(name or "").strip()
        if not recipe_name:
            raise ValueError("Name the fitting recipe before saving it.")
        data = self._required_morph_data(session)
        state = self._refresh_cached_morph_metadata_locked(session)
        if not state.refit.garment_settings or not state.driver_submesh_indices:
            raise RuntimeError("Bind at least one garment to a body driver before saving a fitting recipe.")
        roles = tuple(sorted(set(state.driver_submesh_indices).union(
            item.submesh_index for item in state.refit.garment_settings
        )))
        neutral = self._native_neutral_mesh_locked(session, roles)
        values = dict(state.values)
        preset = MeshMorphValuePreset(
            preset_id=f"recipe-{uuid4().hex[:12]}", name=recipe_name,
            profile_id=data.profile.profile_id, topology_fingerprint=data.profile.topology_fingerprint,
            values=tuple((item.definition_id, values.get(item.definition_id, 0.0)) for item in data.profile.definitions),
            **self._morph_layer_preset_fields_locked(session),
        )
        recipe = MeshMorphFittingRecipe(
            recipe_id=recipe_id or f"recipe-{uuid4().hex}", name=recipe_name,
            profile=data.profile, preset=preset,
            driver_submesh_indices=state.driver_submesh_indices,
            garment_settings=state.refit.garment_settings,
            garment_regions=state.refit.garment_regions,
            topology_fingerprint=mesh_morph_role_topology_fingerprint(neutral, roles),
            base_geometry_fingerprint=mesh_morph_base_fingerprint(neutral, roles),
        )
        validate_mesh_morph_fitting_recipe(neutral, recipe)
        return recipe

    def export_refit_recipe(self, session_id, path, name):
        if not str(path or "").strip():
            raise ValueError("Choose a fitting recipe destination.")
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            recipe = self._build_refit_recipe_locked(session, name)
        destination = Path(path).expanduser()
        if destination.suffix.lower() != ".json":
            raise ValueError("Fitting recipes must be saved to a .json file.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with atomic_text_writer(destination) as stream:
            write_json(stream, fitting_recipe_payload(recipe, streaming=True))
        return str(destination)

    def save_refit_setup(self, session_id, name):
        """Save one identity-bound setup in the reversible settings-owned tree."""
        setup_name = str(name or "").strip()
        if not setup_name or len(setup_name) > 128:
            raise ValueError("Name the fitting setup using between 1 and 128 characters.")
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)

            def save():
                from cdmw.services.mesh_service_morph import _service_call
                recipe = self._build_refit_recipe_locked(
                    session, setup_name, recipe_id=f"setup-{uuid4().hex}",
                )
                document = capture_profile_json(fitting_recipe_payload(recipe, streaming=True))
                relative = f"fitting_setups/{recipe.recipe_id}.json"
                _existed, previous_files, _fingerprint = _service_call(
                    "_mesh_morph_profile_directory_state", self._profile_root(),
                )
                candidate = dict(previous_files)
                if relative in candidate:
                    raise RuntimeError("The new fitting setup identity already exists.")
                candidate[relative] = document
                _validated_mesh_morph_profile_files(tuple(sorted(candidate.items())))
                destination = self._profile_root() / "fitting_setups" / f"{recipe.recipe_id}.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                with atomic_binary_writer(destination) as stream:
                    write_profile_file(stream, document)
                self._authoring_data_locked(session).refit_setup_cache = None
                return self._result(session, "morph_save_refit_setup")

            return self._morph_authoring_transaction_locked(
                session, "morph_save_refit_setup", f"Save Fitting Setup {setup_name}", save,
                include_profile_files=True,
            )

    def _carry_refit_setup_cache_locked(self, session, previous_revision):
        """Carry a proof only across a caller-verified neutral-preserving edit."""
        data = self._morph_sessions.get(session.session_id)
        cache = getattr(data, "refit_setup_cache", None)
        if isinstance(cache, _RefitSetupCache) and cache.revision == previous_revision:
            cache.revision = session.revision

    def _matching_refit_setup_state_fields_locked(self, session, data, raw_state):
        """Expose names and garment roles from the same verified setup snapshot."""
        matches = self._matching_refit_setups_locked(session, data, raw_state)
        cache = getattr(data, "refit_setup_cache", None)
        garments = ()
        if matches and isinstance(cache, _RefitSetupCache):
            recipes = {recipe.recipe_id: recipe for recipe in cache.recipes}
            garments = tuple(
                (identifier, tuple(item.submesh_index for item in recipes[identifier].garment_settings))
                for identifier, _name in matches
            )
        return {"matching_recipes": matches, "matching_recipe_garments": garments}

    def _matching_refit_setups_locked(self, session, data, raw_state):
        """Cache exact validation by saved content, editor revision and driver roles."""
        from cdmw.services.mesh_service_morph import _service_call, mesh_morph_profile_lock
        if data.authoring_operation or data.topology_invalidated or raw_state.get("busy"):
            return ()
        try:
            driver_roles = _strict_indices(
                raw_state.get("driver_submesh_indices") or (),
                label="Current setup drivers", count=len(session.working_mesh.submeshes),
                nonempty=False,
            )
        except (TypeError, ValueError):
            return ()
        cache = getattr(data, "refit_setup_cache", None)
        try:
            with mesh_morph_profile_lock(self._profile_root()):
                _exists, files, fingerprint = _service_call(
                    "_mesh_morph_profile_directory_state", self._profile_root() / "fitting_setups",
                )
            if (
                isinstance(cache, _RefitSetupCache)
                and cache.revision == session.revision
                and cache.tree_fingerprint == fingerprint
                and cache.driver_roles == driver_roles
            ):
                return cache.matches
            if isinstance(cache, _RefitSetupCache) and cache.tree_fingerprint == fingerprint:
                recipes, diagnostics = cache.recipes, cache.diagnostics
            else:
                recipes, diagnostics = _saved_setup_records(files)
            valid_roles = {
                _recipe_roles(recipe) for recipe in recipes
                if all(index < len(session.working_mesh.submeshes) for index in _recipe_roles(recipe))
            }
            neutral = None
            identities = ()
            if valid_roles:
                union = tuple(sorted({index for roles in valid_roles for index in roles}))
                neutral = self._native_neutral_mesh_locked(session, union)
                identities = tuple(
                    (roles, mesh_morph_role_topology_fingerprint(neutral, roles),
                     mesh_morph_base_fingerprint(neutral, roles))
                    for roles in sorted(valid_roles)
                )
            matches = []
            for recipe in recipes:
                if _recipe_roles(recipe) not in valid_roles:
                    continue
                try:
                    validate_mesh_morph_fitting_recipe(neutral, recipe)
                except (TypeError, ValueError, IndexError, OverflowError):
                    continue
                matches.append((recipe.recipe_id, recipe.name))
            matched = tuple(sorted(matches, key=lambda item: (item[1].casefold(), item[0])))
            data.refit_setup_cache = _RefitSetupCache(
                session.revision, fingerprint, driver_roles, recipes, identities, matched, diagnostics,
            )
            return matched
        except (OSError, RuntimeError, UnicodeError, TypeError, ValueError, OverflowError):
            data.refit_setup_cache = None
            return ()

    def apply_refit_setup(self, session_id, recipe_id, garment_submesh_indices=()):
        """Resolve only an owned setup ID, then revalidate its current bytes and roles."""
        from cdmw.services.mesh_service_morph import _service_call, mesh_morph_profile_lock
        identifier = _saved_setup_id(recipe_id)
        session = self._session(session_id)
        with session.export_lock, mesh_morph_profile_lock(self._profile_root()):
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            _existed, files, _fingerprint = _service_call(
                "_mesh_morph_profile_directory_state", self._profile_root(),
            )
            encoded = dict(files).get(f"fitting_setups/{identifier}.json")
            if encoded is None:
                raise ValueError("This saved fitting setup is no longer available.")
            with profile_file_text(encoded) as stream:
                recipe = fitting_recipe_from_payload(_read_object_stream(stream, parse_definitions=True))
            if recipe.recipe_id != identifier:
                raise ValueError("The saved fitting setup identity does not match its file.")
            return self._apply_refit_recipe_locked(
                session, recipe, garment_submesh_indices,
                action="morph_apply_refit_setup", label=f"Apply Fitting Setup {recipe.name}",
            )

    def import_refit_recipe(self, session_id, path, garment_submesh_indices=()):
        """Validate and apply a portable setup to selected loaded garment roles."""
        recipe = read_fitting_recipe(path)
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            return self._apply_refit_recipe_locked(
                session, recipe, garment_submesh_indices,
                action="morph_import_recipe", label=f"Apply Fitting Recipe {recipe.name}",
            )

    def _apply_refit_recipe_locked(
        self, session, recipe, garment_submesh_indices, *, action, label,
    ):
        state = self._refresh_cached_morph_metadata_locked(session)
        recipe_garments = tuple(item.submesh_index for item in recipe.garment_settings)
        targets = _strict_indices(
            garment_submesh_indices or recipe_garments,
            label="Recipe target garments", count=len(session.working_mesh.submeshes),
        )
        if not set(targets).issubset(recipe_garments):
            raise ValueError("Selected garment parts are absent from this fitting recipe.")
        current_profile = getattr(self._morph_sessions.get(session.session_id), "profile", None)
        retained_definitions = tuple(
            definition for definition in current_profile.definitions
            if any(field.submesh_index not in targets for field in definition.garment_corrections)
        ) if current_profile is not None else ()
        if retained_definitions and (
            mesh_morph_profile_definition_fingerprint(current_profile)
            != mesh_morph_profile_definition_fingerprint(recipe.profile)
        ):
            raise ValueError("This setup changes body definitions used by unselected garment corrections. Include those garment Parts before applying it.")
        roles = tuple(sorted(set(_recipe_roles(recipe)).union(
            field.submesh_index
            for definition in retained_definitions for field in definition.garment_corrections
        )))
        neutral = self._native_neutral_mesh_locked(session, roles)
        validate_mesh_morph_fitting_recipe(neutral, recipe)
        # Verify the complete original correction identity before retaining a
        # subset and computing its new fingerprint. A stale field is not rebased.
        for definition in retained_definitions:
            validate_morph_definition_geometry(neutral, definition)
        retained = {
            definition.definition_id: tuple(
                field for field in definition.garment_corrections if field.submesh_index not in targets
            )
            for definition in retained_definitions
        }
        scoped_profile = replace(recipe.profile, definitions=tuple(
            with_morph_garment_corrections(
                definition, neutral,
                tuple(field for field in definition.garment_corrections if field.submesh_index in targets)
                + retained.get(definition.definition_id, ()),
            )
            for definition in recipe.profile.definitions
        ))
        unrelated = set(state.refit.garment_submesh_indices).difference(targets)
        if unrelated and tuple(state.driver_submesh_indices) != recipe.driver_submesh_indices:
            raise ValueError("This recipe would replace the driver of other bound garments. Use a session with matching driver roles.")
        corrections = {field.submesh_index for definition in scoped_profile.definitions for field in definition.garment_corrections}
        if not corrections.issubset(set(targets).union(state.refit.garment_submesh_indices)):
            raise ValueError("Include every unbound garment referenced by the recipe's saved corrections.")

        def apply():
            from cdmw.services.mesh_service_morph import _service_call
            profile, preset = scoped_profile, recipe.preset
            _existed, previous_files, _fingerprint = _service_call("_mesh_morph_profile_directory_state", self._profile_root())
            files = dict(previous_files)
            data = self._authoring_data_locked(session)
            relative, document = mesh_morph_profile_file_data(profile)
            existing = data.known_profiles.get(profile.profile_id)
            if (relative in files and files[relative] != document) or (existing is not None and existing != profile):
                profile = replace(profile, profile_id=f"recipe-{uuid4().hex[:12]}", name=f"{profile.name} (recipe)")
                preset = replace(preset, profile_id=profile.profile_id)
            relative, document = mesh_morph_preset_file_data(preset)
            if relative in files and files[relative] != document:
                preset = replace(preset, preset_id=f"recipe-{uuid4().hex[:12]}")
            for relative, document in (
                mesh_morph_profile_file_data(profile),
                mesh_morph_preset_file_data(preset),
            ):
                files[relative] = document
            _validated_mesh_morph_profile_files(tuple(sorted(files.items())))

            results = [self._activate_morph_profile_locked(
                session, profile, record_history=False, preserve_runtime=True,
                values={item.definition_id: 0.0 for item in profile.definitions}, base_mesh=neutral,
            )[0]]

            def run(command, payload):
                report = self._run_morph_command_locked(
                    session, command, payload, history_label=label, record_history=False,
                )
                # Native acceptance precedes the retained Python state update;
                # both must be installed before any metadata refresh compares them.
                if command == "morph_apply_preset":
                    self._install_morph_preset_layers_locked(session, preset)
                results.append(self._morph_result_and_state_locked(session, command, report)[0])

            if tuple(state.driver_submesh_indices) != recipe.driver_submesh_indices:
                if state.refit.garment_submesh_indices:
                    run("morph_clear_refit", {})
                run("morph_set_driver", {"submesh_indices": list(recipe.driver_submesh_indices)})
            regions = dict(recipe.garment_regions)
            for index in targets:
                payload = {"garment_submesh_indices": [index], "preserve_existing": True}
                if regions.get(index):
                    payload["driver_regions"] = [
                        {"submesh_index": item.submesh_index, "vertex_indices": list(item.vertex_indices)}
                        for item in regions[index]
                    ]
                run("morph_bind", payload)
            run("morph_configure_refit", _refit_settings_batch_payload([
                item for item in recipe.garment_settings
                if item.submesh_index in targets
            ]))
            run("morph_apply_preset", {"preset_id": preset.preset_id, "values": dict(preset.values)})
            save_mesh_morph_profile(self._profile_root(), profile)
            save_mesh_morph_preset(self._profile_root(), preset)
            data = self._authoring_data_locked(session)
            data.topology_mesh = neutral
            data.preset_id = preset.preset_id
            data.known_presets[(profile.profile_id, preset.preset_id)] = preset
            data.refit_setup_cache = None
            return _merge_edit_results(results)

        return self._morph_authoring_transaction_locked(
            session, action, label, apply, include_profile_files=True,
        )
