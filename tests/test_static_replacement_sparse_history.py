from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser import static_replacement_sparse_history as sparse_history


def _snapshot(snapshot_id: str) -> dict[str, object]:
    return {
        "kind": "native_sparse_vertex_delta",
        "before_positions_by_submesh": {
            0: {
                "groups": [
                    {
                        "vertex_indices": (1, 2),
                        "native_sparse_snapshot_id": snapshot_id,
                    }
                ]
            }
        },
    }


def setup_function() -> None:
    sparse_history._SPARSE_VERTEX_SNAPSHOT_REFCOUNTS.clear()


def test_sparse_vertex_snapshot_ids_read_resident_group_handles() -> None:
    assert sparse_history.sparse_vertex_snapshot_ids(_snapshot("resident-a")) == {"resident-a"}
    assert sparse_history.sparse_vertex_snapshot_ids({"kind": "full_mesh"}) == set()


def test_release_disposes_after_last_retained_snapshot_reference(monkeypatch) -> None:
    disposed: list[str] = []
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.dispose_native_mesh_sparse_vertex_snapshot",
        lambda snapshot_id: disposed.append(str(snapshot_id)) or True,
    )

    first = _snapshot("resident-shared")
    second = _snapshot("resident-shared")
    sparse_history.retain_sparse_vertex_snapshot(first)
    sparse_history.retain_sparse_vertex_snapshot(second)

    sparse_history.release_sparse_vertex_snapshot(first)
    assert disposed == []

    sparse_history.release_sparse_vertex_snapshot(second)
    assert disposed == ["resident-shared"]


def test_stack_replace_keeps_retained_snapshots_and_releases_removed_handles(monkeypatch) -> None:
    disposed: list[str] = []
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.dispose_native_mesh_sparse_vertex_snapshot",
        lambda snapshot_id: disposed.append(str(snapshot_id)) or True,
    )

    kept = _snapshot("resident-kept")
    dropped = _snapshot("resident-dropped")
    added = _snapshot("resident-added")
    stack = [kept, dropped]
    sparse_history.retain_sparse_vertex_snapshot_stack(stack)

    sparse_history.replace_sparse_vertex_snapshot_stack(stack, [kept, added])

    assert stack == [kept, added]
    assert disposed == ["resident-dropped"]

    sparse_history.clear_sparse_vertex_snapshot_stack(stack)
    assert disposed[0] == "resident-dropped"
    assert set(disposed[1:]) == {"resident-added", "resident-kept"}
    assert stack == []


def test_mesh_history_snapshot_release_disposes_native_submesh_snapshot(monkeypatch) -> None:
    disposed: list[str] = []
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.dispose_native_mesh_submesh_snapshot",
        lambda snapshot: disposed.append(str(snapshot["handle"]["id"])) or True,
    )

    snapshot = {
        "kind": "native_submesh_snapshot",
        "handle": {"id": "resident-mesh"},
    }

    sparse_history.release_mesh_history_snapshot(snapshot)

    assert disposed == ["resident-mesh"]


def test_mesh_history_stack_clear_releases_sparse_and_native_handles(monkeypatch) -> None:
    disposed_sparse: list[str] = []
    disposed_submesh: list[str] = []
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.dispose_native_mesh_sparse_vertex_snapshot",
        lambda snapshot_id: disposed_sparse.append(str(snapshot_id)) or True,
    )
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.dispose_native_mesh_submesh_snapshot",
        lambda snapshot: disposed_submesh.append(str(snapshot["handle"]["id"])) or True,
    )

    stack = [
        _snapshot("resident-sparse"),
        {"kind": "native_submesh_snapshot", "handle": {"id": "resident-submesh"}},
    ]
    sparse_history.retain_mesh_history_snapshot(stack[0])

    sparse_history.clear_mesh_history_snapshot_stack(stack)

    assert disposed_sparse == ["resident-sparse"]
    assert disposed_submesh == ["resident-submesh"]
    assert stack == []


def test_mesh_history_stack_replace_releases_removed_native_handles(monkeypatch) -> None:
    disposed: list[str] = []
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.dispose_native_mesh_submesh_snapshot",
        lambda snapshot: disposed.append(str(snapshot["handle"]["id"])) or True,
    )

    kept = {"kind": "native_submesh_snapshot", "handle": {"id": "resident-kept"}}
    dropped = {"kind": "native_submesh_snapshot", "handle": {"id": "resident-dropped"}}
    added = {"kind": "native_submesh_snapshot", "handle": {"id": "resident-added"}}
    stack = [kept, dropped]

    sparse_history.replace_mesh_history_snapshot_stack(stack, [kept, added])

    assert stack == [kept, added]
    assert disposed == ["resident-dropped"]


def test_sparse_history_restore_blocks_python_fallback_when_native_available(monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    mesh = SimpleNamespace(total_vertices=3, total_faces=1, submeshes=())
    monkeypatch.setattr("cdmw.modding.mesh_native_core.native_mesh_core_available", lambda: True)
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.record_native_mesh_core_fallback",
        lambda operation, _reason, **details: events.append((str(operation), details)),
    )

    allowed = sparse_history.allow_python_sparse_history_restore_fallback(
        mesh,
        (0,),
        "history.static_sparse_restore",
    )

    assert not allowed
    assert events == [
        (
            "history.static_sparse_restore.blocked",
            {"vertex_count": 3, "face_count": 1, "submesh_indices": (0,)},
        )
    ]


def test_mesh_history_snapshot_blocks_python_fallback_when_native_available(monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    mesh = SimpleNamespace(total_vertices=3, total_faces=1, submeshes=())
    monkeypatch.setattr("cdmw.modding.mesh_native_core.native_mesh_core_available", lambda: True)
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.record_native_mesh_core_fallback",
        lambda operation, _reason, **details: events.append((str(operation), details)),
    )

    allowed = sparse_history.allow_python_mesh_history_snapshot_fallback(
        mesh,
        "history.static_geometry_snapshot",
    )

    assert not allowed
    assert events == [
        (
            "history.static_geometry_snapshot.blocked",
            {"vertex_count": 3, "face_count": 1},
        )
    ]


def test_full_mesh_clone_blocks_python_fallback_with_operation_reason(monkeypatch) -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    mesh = SimpleNamespace(total_vertices=3, total_faces=1, submeshes=())
    monkeypatch.setattr("cdmw.modding.mesh_native_core.native_mesh_core_available", lambda: True)
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.record_native_mesh_core_fallback",
        lambda operation, reason, **details: events.append((str(operation), str(reason), details)),
    )

    allowed = sparse_history.allow_python_full_mesh_clone_fallback(
        mesh,
        "live_edit.static_stroke_clone",
        "Python live stroke clone fallback blocked while native mesh core is available",
    )

    assert not allowed
    assert events == [
        (
            "live_edit.static_stroke_clone.blocked",
            "Python live stroke clone fallback blocked while native mesh core is available",
            {"vertex_count": 3, "face_count": 1},
        )
    ]


def test_static_replacement_clone_uses_native_snapshot_before_python(monkeypatch) -> None:
    from cdmw.modding.mesh_parser import ParsedMesh

    mesh = ParsedMesh(path="source.pam", format="pam")
    snapshot = {"kind": "native_submesh_snapshot", "handle": {"id": "setup-clone"}}
    disposed: list[object] = []
    invalidated: list[tuple[object, tuple[int, ...]]] = []

    monkeypatch.setattr("cdmw.modding.mesh_native_core.snapshot_native_mesh_submeshes", lambda _mesh: snapshot)

    def restore(restored: ParsedMesh, _snapshot: object) -> bool:
        restored.path = "restored.pam"
        restored.format = "pam"
        restored.submeshes = []
        return True

    monkeypatch.setattr("cdmw.modding.mesh_native_core.restore_native_mesh_submesh_snapshot", restore)
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.invalidate_native_mesh_session_submeshes",
        lambda restored, indices: invalidated.append((restored, tuple(indices))),
    )
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.dispose_native_mesh_submesh_snapshot",
        lambda native_snapshot: disposed.append(native_snapshot) or True,
    )
    monkeypatch.setattr(
        "cdmw.modding.mesh_deformer.clone_mesh_for_editing",
        lambda _mesh: (_ for _ in ()).throw(AssertionError("Python clone fallback should not run")),
    )

    result = sparse_history.clone_mesh_for_static_replacement_native_first(
        mesh,
        "prompt_setup.replacement_base_clone",
        "fallback blocked",
        allow_python_setup_fallback=True,
    )

    assert isinstance(result, ParsedMesh)
    assert result.path == "restored.pam"
    assert disposed == [snapshot]
    assert invalidated == [(result, ())]


def test_static_replacement_clone_uses_python_for_native_unsupported_setup_mesh(monkeypatch) -> None:
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

    mesh = ParsedMesh(
        path="clone.obj",
        format="obj",
        submeshes=[
            SubMesh(
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2, 3)],  # type: ignore[list-item]
            )
        ],
    )
    fallback_calls: list[object] = []

    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.snapshot_native_mesh_submeshes",
        lambda _mesh: (_ for _ in ()).throw(AssertionError("native snapshot should not run")),
    )
    monkeypatch.setattr(
        "cdmw.modding.mesh_deformer.clone_mesh_for_editing",
        lambda candidate: fallback_calls.append(candidate) or ParsedMesh(path="cloned.obj", format="obj"),
    )

    result = sparse_history.clone_mesh_for_static_replacement_native_first(
        mesh,
        "prompt_setup.replacement_base_clone",
        "fallback blocked",
        allow_python_setup_fallback=True,
    )

    assert isinstance(result, ParsedMesh)
    assert result.path == "cloned.obj"
    assert fallback_calls == [mesh]


def test_static_replacement_clone_uses_custom_fallback_guard(monkeypatch) -> None:
    mesh = SimpleNamespace(submeshes=())
    fallback_calls: list[object] = []

    monkeypatch.setattr("cdmw.modding.mesh_native_core.snapshot_native_mesh_submeshes", lambda _mesh: None)
    monkeypatch.setattr(
        "cdmw.modding.mesh_deformer.clone_mesh_for_editing",
        lambda _mesh: (_ for _ in ()).throw(AssertionError("Python clone fallback should be guarded")),
    )

    result = sparse_history.clone_mesh_for_static_replacement_native_first(
        mesh,
        "morph_slider.bake_clone",
        "fallback blocked",
        fallback_allowed=lambda candidate: fallback_calls.append(candidate) or False,
    )

    assert result is None
    assert fallback_calls == [mesh]


def test_morph_slider_bake_clone_blocks_python_fallback(monkeypatch) -> None:
    events: list[tuple[str, str, dict[str, object]]] = []
    mesh = SimpleNamespace(total_vertices=3, total_faces=1, submeshes=())
    monkeypatch.setattr("cdmw.modding.mesh_native_core.native_mesh_core_available", lambda: True)
    monkeypatch.setattr(
        "cdmw.modding.mesh_native_core.record_native_mesh_core_fallback",
        lambda operation, reason, **details: events.append((str(operation), str(reason), details)),
    )

    allowed = sparse_history.allow_python_full_mesh_clone_fallback(
        mesh,
        "morph_slider.bake_clone",
        "Python morph-slider bake clone fallback blocked while native mesh core is available",
    )

    assert not allowed
    assert events == [
        (
            "morph_slider.bake_clone.blocked",
            "Python morph-slider bake clone fallback blocked while native mesh core is available",
            {"vertex_count": 3, "face_count": 1},
        )
    ]
