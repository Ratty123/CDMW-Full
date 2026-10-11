"""Saved fitting setup storage, matching and authoring transaction contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import re

import pytest

from cdmw.domain.mesh import mesh_morph_driver_topology_fingerprint
from cdmw.domain.mesh.morph_layers import compose_mesh_morph_values
from cdmw.services.mesh_service_history_files import (
    _mesh_morph_profile_directory_state,
    _restore_mesh_morph_profile_directory_state,
)
from cdmw.services.mesh_service_morph import _MeshMorphSessionData
from cdmw.services.mesh_service_morph_recipes import (
    read_fitting_recipe, serialized_fitting_recipe,
)
import cdmw.services.mesh_service_morph_recipes as recipe_module
from tests.test_mesh_morph_authoring_service import Harness
from tests.test_mesh_morph_layers import _profile as _layer_profile


class SetupHarness(Harness):
    def __init__(self, root):
        super().__init__(root)
        self.neutral_queries = 0
        self.fail_publication = False

    def _native_neutral_mesh_locked(self, session, indices):
        self.neutral_queries += 1
        return super()._native_neutral_mesh_locked(session, indices)

    def _refresh_cached_morph_metadata_locked(self, session):
        state = super()._refresh_cached_morph_metadata_locked(session)
        fields = self._morph_layer_state_fields_locked(
            session, self.data, self.data.profile, dict(state.values),
        )
        matching = self._matching_refit_setups_locked(
            session, self.data, {"driver_submesh_indices": state.driver_submesh_indices},
        )
        self.data.state = replace(state, matching_recipes=matching, **fields)
        return self.data.state

    def _capture_morph_profile_history_locked(self, session, **kwargs):
        original = super()._capture_morph_profile_history_locked(session, **kwargs)
        return original, _mesh_morph_profile_directory_state(self.root)

    def _publish_morph_profile_history_locked(self, session, snapshot, *, base_revision):
        if self.fail_publication:
            raise RuntimeError("injected setup publication failure")
        return super()._publish_morph_profile_history_locked(
            session, snapshot, base_revision=base_revision,
        )

    def restore(self, snapshot):
        original, (existed, files, _old_fingerprint) = snapshot
        _restore_mesh_morph_profile_directory_state(
            self.root, existed=existed, files=files,
            expected_fingerprint=_mesh_morph_profile_directory_state(self.root)[2],
        )
        self._morph_sessions["mock"], self.session.working_mesh, self.session.revision = deepcopy(original)

    def _rollback_unpublished_morph_profile_history_locked(self, session, snapshot):
        self.rollbacks += 1
        self.restore(snapshot)


def _service(tmp_path):
    return SetupHarness(tmp_path / "mesh_slider_profiles")


def _saved_path(service, state):
    identifier, _name = state.matching_recipes[-1]
    return identifier, service.root / "fitting_setups" / f"{identifier}.json"


def test_save_setup_uses_opaque_identity_and_one_reversible_tree_transaction(tmp_path):
    service = _service(tmp_path)
    original_mesh = deepcopy(service.session.working_mesh)
    service.data.state = replace(service.data.state, values=(("lift", 45.0),))
    result, state = service.save_refit_setup("mock", "Travel outfit")
    assert result.ok and result.action == "morph_save_refit_setup"
    assert len(service.session.undo_stack) == 1
    identifier, path = _saved_path(service, state)
    assert re.fullmatch(r"setup-[0-9a-f]{32}", identifier)
    assert path.is_file()
    recipe = read_fitting_recipe(path)
    assert recipe.recipe_id == identifier and recipe.name == "Travel outfit"
    assert recipe.preset.values == (("lift", 45.0),)
    assert recipe.garment_settings == state.refit.garment_settings
    assert service.session.working_mesh == original_mesh
    saved_tree = _mesh_morph_profile_directory_state(service.root)
    before = service.session.undo_stack[-1]
    redo = (
        (deepcopy(service.data), deepcopy(service.session.working_mesh), service.session.revision),
        saved_tree,
    )
    service.restore(before)
    assert not path.exists()
    service.restore(redo)
    assert path.is_file()
    assert _mesh_morph_profile_directory_state(service.root)[2] == saved_tree[2]


def test_duplicate_setup_names_get_distinct_saved_identities(tmp_path):
    service = _service(tmp_path)
    service.save_refit_setup("mock", "Favorite")
    _result, state = service.save_refit_setup("mock", "Favorite")
    assert len(state.matching_recipes) == 2
    assert len({identifier for identifier, _name in state.matching_recipes}) == 2
    assert {name for _identifier, name in state.matching_recipes} == {"Favorite"}


@pytest.mark.parametrize("name", ["", " ", "x" * 129])
def test_invalid_setup_name_fails_before_history_or_files(tmp_path, name):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="between 1 and 128"):
        service.save_refit_setup("mock", name)
    assert not service.captures and not service.root.exists()


@pytest.mark.parametrize("identifier", ["../preset", "C:/private.json", "setup-" + "g" * 32, "", 123])
def test_setup_application_accepts_only_owned_opaque_ids(tmp_path, identifier):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="matching list"):
        service.apply_refit_setup("mock", identifier)
    assert not service.commands and not service.captures and not service.root.exists()


@pytest.mark.parametrize("change", ["neutral", "faces", "source_map", "weights", "palette"])
def test_matching_and_apply_revalidate_neutral_topology_and_source_skin_identity(tmp_path, change):
    service = _service(tmp_path)
    _result, state = service.save_refit_setup("mock", "Exact outfit")
    identifier, _path = _saved_path(service, state)
    part = service.neutral.submeshes[2]
    if change == "neutral":
        part.vertices[0] = (0.0, 0.0, 1.0)
    elif change == "faces":
        part.faces[0] = (0, 2, 1)
    elif change == "source_map":
        part.source_vertex_map[0] = 1
    elif change == "weights":
        part.bone_weights[0] = (0.25, 0.75)
    else:
        part.source_bone_palette = (12, 24)
    service.session.revision += 1
    assert service._refresh_cached_morph_metadata_locked(service.session).matching_recipes == ()
    captures = service.captures
    with pytest.raises(ValueError, match="does not match"):
        service.apply_refit_setup("mock", identifier)
    assert service.captures == captures and not service.commands


def test_scalar_cache_carry_avoids_parse_and_neutral_query_but_generic_edits_expire(tmp_path, monkeypatch):
    service = _service(tmp_path)
    _result, state = service.save_refit_setup("mock", "Cached outfit")
    # Publication advanced the editor revision after its last metadata refresh.
    service._refresh_cached_morph_metadata_locked(service.session)
    expected = state.matching_recipes
    parses = []
    original = recipe_module._saved_setup_records

    def counted(files):
        parses.append(1)
        return original(files)

    monkeypatch.setattr(recipe_module, "_saved_setup_records", counted)
    baseline_queries = service.neutral_queries
    for percent in (10.0, 25.0, 60.0):
        previous = service.session.revision
        service.session.revision += 1
        service.data.state = replace(service.data.state, values=(("lift", percent),))
        service._carry_refit_setup_cache_locked(service.session, previous)
        assert service._refresh_cached_morph_metadata_locked(service.session).matching_recipes == expected
    assert not parses and service.neutral_queries == baseline_queries
    service.session.revision += 1  # An unrelated coordinate edit is not carried.
    previous = service.session.revision
    service.session.revision += 1
    service._carry_refit_setup_cache_locked(service.session, previous)
    service._refresh_cached_morph_metadata_locked(service.session)
    assert not parses
    assert service.neutral_queries == baseline_queries + 1


def test_changed_setup_content_reparses_and_validates_before_updating_list(tmp_path, monkeypatch):
    service = _service(tmp_path)
    _result, state = service.save_refit_setup("mock", "Original")
    identifier, path = _saved_path(service, state)
    service._refresh_cached_morph_metadata_locked(service.session)
    queries = service.neutral_queries
    recipe = replace(read_fitting_recipe(path), name="Renamed externally")
    path.write_text(serialized_fitting_recipe(recipe), encoding="utf-8")
    refreshed = service._refresh_cached_morph_metadata_locked(service.session)
    assert refreshed.matching_recipes == ((identifier, "Renamed externally"),)
    assert service.neutral_queries == queries + 1
    path.write_text("invalid JSON", encoding="utf-8")
    assert service._refresh_cached_morph_metadata_locked(service.session).matching_recipes == ()
    with pytest.raises(ValueError):
        service.apply_refit_setup("mock", identifier)


def test_saved_setup_file_identity_must_match_the_requested_id(tmp_path):
    service = _service(tmp_path)
    _result, state = service.save_refit_setup("mock", "Own identity")
    identifier, path = _saved_path(service, state)
    payload = json.loads(path.read_text())
    payload["recipe_id"] = "setup-" + "1" * 32
    path.write_text(json.dumps(payload))
    assert service._refresh_cached_morph_metadata_locked(service.session).matching_recipes == ()
    with pytest.raises(ValueError, match="identity"):
        service.apply_refit_setup("mock", identifier)
    assert not service.commands


def test_failed_setup_save_restores_previous_tree_and_layer_state(tmp_path):
    service = _service(tmp_path)
    service.save_refit_setup("mock", "Existing")
    previous_tree = _mesh_morph_profile_directory_state(service.root)
    previous_profile = service.data.profile
    count = len(service.session.undo_stack)
    service.fail_publication = True
    with pytest.raises(RuntimeError, match="publication failure"):
        service.save_refit_setup("mock", "Failing")
    assert _mesh_morph_profile_directory_state(service.root) == previous_tree
    assert service.data.profile == previous_profile
    assert len(service.session.undo_stack) == count
    assert service.rollbacks == 1


def test_saved_setup_apply_preserves_unselected_garment_settings(tmp_path):
    service = _service(tmp_path)
    service.data.state = replace(service.data.state, values=(("lift", 55.0),))
    _result, state = service.save_refit_setup("mock", "Partial fit")
    identifier, _path = _saved_path(service, state)
    untouched = service.data.state.refit.garment_settings[1]
    result, applied = service.apply_refit_setup("mock", identifier, (2,))
    assert result.ok and result.action == "morph_apply_refit_setup"
    binds = [payload for command, payload, _kwargs in service.commands if command == "morph_bind"]
    assert [item["garment_submesh_indices"] for item in binds] == [[2]]
    assert binds[0]["preserve_existing"] is True
    assert applied.refit.garment_settings[1] == untouched
    assert applied.values == (("lift", 55.0),)


def test_setup_layer_roundtrip_and_collision_install_before_state_refresh(tmp_path):
    service = _service(tmp_path)
    profile = _layer_profile()
    profile = replace(profile, topology_fingerprint=mesh_morph_driver_topology_fingerprint(
        service.neutral, profile.definitions,
    ))
    manual = {item.definition_id: 0.0 for item in profile.definitions}
    manual["thigh_l_size"] = -20.0
    manual["thigh_r_size"] = 60.0
    macros = {"waist_shape": 40.0, "hip_thigh_transition": 20.0}
    values = compose_mesh_morph_values(profile, manual, macros, symmetry_enabled=True)
    service.data.profile = profile
    service.data.known_profiles[profile.profile_id] = profile
    service.data.manual_values = manual
    service.data.macro_values = macros
    service.data.symmetry_enabled = True
    service.data.state = replace(
        service.data.state, profile_id=profile.profile_id, definitions=profile.definitions,
        values=tuple(values.items()),
    )
    _result, state = service.save_refit_setup("mock", "Layered fit")
    identifier, path = _saved_path(service, state)
    stored = read_fitting_recipe(path)
    assert dict(stored.preset.manual_values) == manual
    assert dict(stored.preset.macro_values) == macros and stored.preset.symmetry_enabled
    service.data.known_profiles[profile.profile_id] = replace(profile, name="Conflicting local name")
    service.data.manual_values = None
    service.data.macro_values = {}
    service.data.symmetry_enabled = False
    service.data.state = replace(service.data.state, values=tuple((key, 0.0) for key in values))
    result, restored = service.apply_refit_setup("mock", identifier)
    assert result.ok
    assert restored.profile_id != profile.profile_id
    assert service.data.manual_values == manual
    assert service.data.macro_values == macros and service.data.symmetry_enabled
    assert dict(restored.values) == values
    assert dict(restored.manual_values) == manual


def test_saved_setups_remain_discoverable_without_an_active_profile(tmp_path):
    service = _service(tmp_path)
    _result, state = service.save_refit_setup("mock", "Return later")
    expected = state.matching_recipes
    service._morph_sessions["mock"] = _MeshMorphSessionData(state=replace(
        service.data.state, profile_id="", definitions=(), values=(), driver_submesh_indices=(),
    ))
    assert service._refresh_cached_morph_metadata_locked(service.session).matching_recipes == expected
