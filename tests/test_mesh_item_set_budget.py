import itertools
import random

from cdmw.services.mesh_item_set_budget import largest_fitting_subset, prepare_item_set_budget


def test_subset_matches_exhaustive_count_for_independent_resource_limits():
    randomizer = random.Random(8)
    for _ in range(40):
        costs = [(randomizer.randrange(1, 30), randomizer.randrange(1, 30), randomizer.randrange(1, 50)) for _ in range(9)]
        limits = (70, 80, 150)
        expected = max(sum(mask) for mask in itertools.product((0, 1), repeat=len(costs))
                       if all(sum(row[d] for row, active in zip(costs, mask) if active) <= limits[d] for d in range(3)))
        chosen = largest_fitting_subset(costs, limits)
        assert len(chosen) == expected
        assert all(sum(costs[i][d] for i in chosen) <= limits[d] for d in range(3))
    assert len(largest_fitting_subset([(1, 1, 2)] * 32, (16, 32, 40))) == 16


def test_measured_session_budget_keeps_primary_and_bounded_named_reference(tmp_path, monkeypatch):
    from tests.test_mesh_item_set_editing import _set
    from cdmw.services import mesh_rust_authoring as a
    (tmp_path / "source").mkdir()
    _source, service, key, context = _set(tmp_path / "source")
    root = tmp_path / "package"
    root.mkdir()
    sources = [(asset.entry, asset.source, None, None) for asset in context.assets]
    sizes = []
    for _entry, snapshot, *_ in sources:
        geometry = len(a.encode_mesh_document(a._mesh_document_arrays(snapshot.mesh), max_payload_bytes=a.RUST_MESH_MAX_PAYLOAD_BYTES))
        channels = len(a._canonical_json_bytes(a._mesh_channel_payload(snapshot.mesh, geometry_path="document.bin")))
        sizes.append((geometry, geometry + channels))
    monkeypatch.setattr(a, "_SESSION_MAX_TOTAL_BYTES", a._RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES + sizes[0][1] + sizes[1][0] + 1)
    try:
        admitted, references, materials = prepare_item_set_budget(sources, root, a._session_root_identity(root), None)
        assert admitted == {0}
        assert set(references) == {context.assets[1].entry.identity}
        assert references[context.assets[1].entry.identity].submeshes[0].faces
        assert materials[0] == []
        assert not list(tmp_path.glob("item-set-materials-*"))
    finally:
        service.close_edit_session(key, force_without_saving=True)
