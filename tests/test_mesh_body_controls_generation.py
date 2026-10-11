"""Owned synthetic proof for reachable, source-bound anatomical body controls."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import struct
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh import (
    MeshEditResult, MeshMorphDefinition, MeshMorphProfile, MeshMorphRule,
    MeshMorphState, MeshMorphVertexWeight, MeshRefitBindingSummary,
    MeshRefitGarmentSettings, mesh_morph_driver_topology_fingerprint,
)
from cdmw.modding.mesh_parser import PAC_SKIN_WEIGHT_LAYOUT, ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_archive_refit import ArchiveRefitAsset, ArchiveRefitContext
from cdmw.services.mesh_service_body_controls import MeshBodyControlsMixin


def _skeleton():
    names = ("pelvis", "spine", "clavicle_l", "upperarm_l", "forearm_l", "hand_l", "neck", "head")
    parents = (-1, 0, 1, 2, 3, 4, 1, 6)
    return Skeleton(
        path="owned-fixture.pab", bone_count=8,
        bones=[Bone(
            index=index, name=name, name_hash=0xAB120000 + index * 0x131,
            parent_index=parents[index], position=(float(index), 0.0, 0.0),
        ) for index, name in enumerate(names)],
    )


def _palette_bytes(skeleton, order=(3, 4, 5, 0, 1, 2, 6, 7)):
    payload = bytearray(512)
    struct.pack_into("<H", payload, 32, len(order))
    struct.pack_into(f"<{len(order)}I", payload, 34, *(skeleton.bones[index].name_hash for index in order))
    return bytes(payload)


def _mesh():
    parts = [
        SubMesh(
            name=name, vertices=[(float(index), 0.0, 0.0), (float(index), 1.0, 0.0), (float(index), 0.0, 1.0)],
            faces=[(0, 1, 2)], vertex_count=3, face_count=1,
            bone_indices=[(slot,)] * 3, bone_weights=[(1.0,)] * 3,
            source_vertex_map=[0, 1, 2], source_vertex_map_authority="target_donor_record",
            # Deliberately misleading descriptor metadata. This must never map bones.
            source_bone_palette=(0, 1, 2), source_skin_weight_layout=PAC_SKIN_WEIGHT_LAYOUT,
        )
        for index, (name, slot) in enumerate((("Upper arm", 0), ("Forearm", 1), ("Garment", 2)))
    ]
    return ParsedMesh(format="PAC", path="owned-fixture.pac", submeshes=parts)


class BodyControlsHarness(MeshBodyControlsMixin):
    def __init__(self):
        mesh = _mesh()
        skeleton = _skeleton()
        definition = MeshMorphDefinition(
            definition_id="custom", label="My custom body", category="Authored",
            vertices=(MeshMorphVertexWeight(0, 0, 1.0),),
            pivot=(0.0, 0.0, 0.0),
            local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            rule=MeshMorphRule("move", "y", 0.1),
        )
        profile = MeshMorphProfile(
            profile_id="my-profile", name="My profile", definitions=(definition,),
            topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, (definition,)),
        )
        self.session = SimpleNamespace(
            session_id="owned", export_lock=threading.RLock(), skeleton=skeleton,
            original_data=_palette_bytes(skeleton), working_mesh=mesh,
            base_mesh=deepcopy(mesh), archive_refit_context=None, revision=0,
        )
        self.data = SimpleNamespace(
            profile=profile, known_profiles={profile.profile_id: profile},
            available_profile_ids=(profile.profile_id,),
            state=MeshMorphState(
                profile_id=profile.profile_id, definitions=profile.definitions,
                values=(("custom", 0.0),), driver_submesh_indices=(0, 1),
                refit=MeshRefitBindingSummary(
                    driver_submesh_indices=(0, 1), garment_submesh_indices=(2,),
                    garment_settings=(MeshRefitGarmentSettings(2, intensity_percent=75.0),),
                ),
            ),
        )
        self.activations = []
        self.transactions = []
        self.fail_activation = False
        self.neutral_queries = []

    def _session(self, session_id):
        assert session_id == "owned"
        return self.session

    def _refresh_cached_morph_metadata_locked(self, session):
        return self.data.state

    def _require_baked_morph_definition_edit(self, session):
        if self.data.state.authoring_baseline_ready or self.data.state.correction_definition_id:
            raise RuntimeError("Pending authoring")
        if self.data.state.unbaked:
            raise RuntimeError("Reset or Bake active sliders")

    def _native_neutral_mesh_locked(self, session, indices):
        self.neutral_queries.append(tuple(indices))
        return deepcopy(session.working_mesh)

    def _authoring_data_locked(self, session):
        return self.data

    def _activate_morph_profile_locked(self, session, profile, diagnostics, **kwargs):
        self.activations.append((profile, diagnostics, kwargs))
        self.data.profile = profile
        self.data.known_profiles[profile.profile_id] = profile
        if self.fail_activation:
            raise RuntimeError("Injected native rejection")
        self.data.available_profile_ids = (*self.data.available_profile_ids, profile.profile_id)
        self.data.state = replace(
            self.data.state, profile_id=profile.profile_id,
            definitions=profile.definitions, values=tuple(kwargs["values"].items()),
        )
        return MeshEditResult("morph_upload", "ok", session.revision), self.data.state

    def _morph_authoring_transaction_locked(self, session, action, label, operation):
        before = deepcopy(self.data)
        try:
            result = operation()
        except Exception:
            self.data = before
            raise
        self.transactions.append((action, label, before))
        session.revision += 1
        return replace(result, action=action, revision=session.revision), self.data.state


def test_generation_uses_actual_palette_and_domain_rules_preserving_custom_profile():
    service = BodyControlsHarness()
    old_profile = service.data.profile
    original_mesh = deepcopy(service.session.working_mesh)
    original_refit = service.data.state.refit

    assert service._body_controls_availability_locked(service.session, service.data.state) == (True, "")
    result, state = service.generate_body_morph_controls("owned")

    assert result.ok and result.action == "morph_generate_body_controls"
    ids = {item.definition_id for item in state.definitions}
    assert "upper_arm_l_size" in ids and "forearm_l_size" in ids
    assert not any(identifier.startswith(("pelvis_", "hand_")) for identifier in ids)
    assert {row.submesh_index for item in state.definitions for row in item.vertices} == {0, 1}
    assert all(value == 0.0 for _name, value in state.values)
    assert service.data.profile.profile_id != old_profile.profile_id
    assert service.data.known_profiles[old_profile.profile_id] is old_profile
    assert service.data.state.refit == original_refit
    assert service.session.working_mesh == original_mesh
    assert service.activations[0][2]["preserve_runtime"] is True
    assert service.activations[0][2]["record_history"] is False
    assert service.neutral_queries == [(0, 1)]
    assert len(service.transactions) == 1


def test_generation_obeys_assigned_body_subset_not_part_selection():
    service = BodyControlsHarness()
    service.data.state = replace(service.data.state, driver_submesh_indices=(1,))
    service.session.selection = SimpleNamespace(source_indices=(0, 2))

    _result, state = service.generate_body_morph_controls("owned")

    assert state.definitions
    assert {row.submesh_index for item in state.definitions for row in item.vertices} == {1}
    assert all(item.definition_id.startswith("forearm_l_") for item in state.definitions)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda service: setattr(service.session, "skeleton", None), "matching resolved skeleton"),
        (lambda service: setattr(service.session, "original_data", b""), "source bytes"),
        (lambda service: setattr(service.session, "original_data", bytes(512)), "bone palette did not resolve"),
        (lambda service: setattr(service.session.base_mesh, "format", "OBJ"), "source-owned PAC"),
        (lambda service: setattr(service.data, "state", replace(service.data.state, driver_submesh_indices=())), "Assign the body"),
        (lambda service: setattr(service.session.base_mesh.submeshes[0], "source_skin_weight_layout", ""), "decoded PAC skin layout"),
    ],
)
def test_unavailable_inputs_never_reach_generation_or_transaction(change, reason):
    service = BodyControlsHarness()
    change(service)
    before = deepcopy(service.data)
    available, message = service._body_controls_availability_locked(service.session, service.data.state)

    assert not available and reason in message
    with pytest.raises(ValueError, match=reason):
        service.generate_body_morph_controls("owned")
    assert service.activations == service.transactions == service.neutral_queries == []
    assert service.data == before


def test_unknown_palette_never_uses_descriptor_slots_as_skeleton_indices():
    service = BodyControlsHarness()
    service.session.original_data = bytes(512)
    for part in service.session.working_mesh.submeshes:
        part.source_bone_palette = tuple(range(8))

    with pytest.raises(ValueError, match="Influence slots cannot be guessed"):
        service.generate_body_morph_controls("owned")
    assert not service.activations


@pytest.mark.parametrize("field", ["authoring_baseline_ready", "correction_definition_id", "unbaked"])
def test_pending_authoring_or_active_values_must_be_resolved_first(field):
    service = BodyControlsHarness()
    value = "custom" if field == "correction_definition_id" else True
    service.data.state = replace(service.data.state, **{field: value})

    assert not service._body_controls_availability_locked(service.session, service.data.state)[0]
    with pytest.raises(RuntimeError):
        service.generate_body_morph_controls("owned")
    assert not service.neutral_queries and not service.transactions


@pytest.mark.parametrize("field", ["values", "manual_values", "macro_values"])
def test_mapping_availability_refuses_nonzero_layer_values(field):
    service = BodyControlsHarness()
    state = {"driver_submesh_indices": [0, 1], field: [["control", 10.0]]}
    available, reason = service._body_controls_availability_locked(service.session, state)
    assert not available and "Reset or Bake" in reason


def test_archive_body_part_uses_its_source_palette_in_combined_index_space():
    service = BodyControlsHarness()
    mesh = service.session.working_mesh
    source_a, source_b = deepcopy(mesh), deepcopy(mesh)
    source_a.submeshes = source_a.submeshes[:1]
    source_b.submeshes = source_b.submeshes[1:]
    # Part 1's slot 1 now names upper arm, not the primary source's forearm.
    secondary_bytes = _palette_bytes(service.session.skeleton, order=(4, 3, 5, 0, 1, 2, 6, 7))
    service.session.archive_refit_context = ArchiveRefitContext(assets=(
        ArchiveRefitAsset(SimpleNamespace(path="primary.pac"), SimpleNamespace(mesh=source_a, original_data=service.session.original_data), (0,), "loaded"),
        ArchiveRefitAsset(SimpleNamespace(path="body.pac"), SimpleNamespace(mesh=source_b, original_data=secondary_bytes), (1, 2), "body"),
    ))
    service.data.state = replace(service.data.state, driver_submesh_indices=(1,))

    _result, state = service.generate_body_morph_controls("owned")

    assert all(item.definition_id.startswith("upper_arm_l_") for item in state.definitions)
    assert {row.submesh_index for item in state.definitions for row in item.vertices} == {1}


@pytest.mark.parametrize("change", ["slot", "skin", "topology", "source_map", "unknown_names"])
def test_invalid_source_identity_or_unusable_anatomy_never_publishes(change):
    service = BodyControlsHarness()
    part = service.session.working_mesh.submeshes[0]
    if change == "slot":
        part.bone_indices[0] = (999,)
        service.session.base_mesh.submeshes[0].bone_indices[0] = (999,)
    elif change == "skin":
        part.bone_weights[0] = (0.5,)
    elif change == "topology":
        part.faces = [(0, 2, 1)]
    elif change == "source_map":
        part.source_vertex_map = [1, 0, 2]
    else:
        for bone in service.session.skeleton.bones:
            bone.name = "unknown"
    before = deepcopy(service.data)

    with pytest.raises(ValueError):
        service.generate_body_morph_controls("owned")
    assert not service.transactions and not service.activations
    assert service.data == before


def test_native_activation_rejection_restores_prior_profile_and_availability():
    service = BodyControlsHarness()
    before = deepcopy(service.data)
    service.fail_activation = True

    with pytest.raises(RuntimeError, match="Injected native rejection"):
        service.generate_body_morph_controls("owned")

    assert service.data == before
    assert not service.transactions and service.session.revision == 0


def test_regeneration_creates_another_identity_without_overwriting_a_profile():
    service = BodyControlsHarness()
    _result, first = service.generate_body_morph_controls("owned")
    first_profile = service.data.profile
    _result, second = service.generate_body_morph_controls("owned")

    assert second.profile_id != first.profile_id
    assert service.data.known_profiles[first.profile_id] is first_profile
    assert len(service.transactions) == 2


@pytest.mark.parametrize(
    "cached",
    [
        SimpleNamespace(authoring_baseline=object()),
        SimpleNamespace(correction_capture=object()),
        SimpleNamespace(manual_values={"control": 10.0}),
        SimpleNamespace(macro_values={"control": -10.0}),
    ],
)
def test_native_raw_availability_also_respects_pending_service_metadata(cached):
    service = BodyControlsHarness()
    service._morph_sessions = {"owned": cached}
    available, reason = service._body_controls_availability_locked(
        service.session, {"driver_submesh_indices": [0, 1], "values": {}},
    )
    assert not available and reason
    assert not service.neutral_queries and not service.transactions
