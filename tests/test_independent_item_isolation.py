"""Read-only ownership inspection through real package admission and lowering."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from cdmw.services.independent_item_isolation import inspect_isolation
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.independent_mod_package import migrate_v1, read_v2
from tests.test_independent_items import authored, setup_game
from tests.test_independent_item_regressions import files_in


def json_report(*args, **kwargs):
    return json.loads(json.dumps(inspect_isolation(*args, **kwargs), allow_nan=False))


@pytest.mark.parametrize("target", ["archive", "virtual"])
@pytest.mark.parametrize("reverse", [False, True])
def test_same_name_items_have_separate_ownership_without_a_native_claim(tmp_path, target, reverse):
    from tests.test_independent_item_reference_assessment import imported_plan
    from tests.test_independent_items import imported_game

    plans = tuple(imported_plan(tmp_path / str(index), private_texture=True)[0] for index in range(2))
    packages = tuple(from_plan(plan, uuid4().hex) for plan in plans)
    imported_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    before = files_in(root)
    selected = packages[::-1] if reverse else packages
    report = json_report([package_bytes(package) for package in selected], root, target=target)
    rows = {row["identity"]: row for row in report["packages"]}
    one, two = (rows[package.identity] for package in packages)
    assert one["title"] == two["title"]
    assert one["authoring_template"] == two["authoring_template"] == plans[0].spec.template_key
    assert one["proposed_bindings"]["iteminfo"]["item"] != two["proposed_bindings"]["iteminfo"]["item"]
    paths = [{row["path"] for row in value["private_outputs"]} for value in (one, two)]
    assert paths[0] and paths[1] and paths[0].isdisjoint(paths[1])
    for row in (one, two):
        assert row["contribution_class"] == "new-item"
        assert row["resource_graph"] is not None
        assert row["authoring_template"] not in row["protected_game_records"]["iteminfo"]
        assert row["protected_game_records"]["equiptypeinfo"]
        assert row["protected_game_records"]["statusinfo"]
        assert any(source["path"].endswith("/iteminfo.staticinfobody") for source in row["source_dependencies"])
        assert any(output["path"].endswith(".staticinfobody") for output in row["shared_outputs"])
        assert not row["isolated_new_item"]["admitted"]
        assert "shared-file-composition" in {reason["code"] for reason in row["isolated_new_item"]["reasons"]}
    assert not report["isolated_new_item_admitted"] and not report["published"]
    assert files_in(root) == before


@pytest.mark.parametrize("kind", ["fields", "texture"])
def test_existing_content_is_never_reported_as_an_isolated_new_item(tmp_path, kind):
    from tests.test_independent_item_fields import field_package
    from tests.test_independent_texture_packages import texture_game, texture_package

    root, snapshot = texture_game(tmp_path)
    package = field_package(snapshot) if kind == "fields" else texture_package(snapshot)
    before = files_in(root)
    report = json_report([package_bytes(package)], root)
    row, = report["packages"]
    assert row["contribution_class"] == "stock-edits"
    assert row["proposed_bindings"] == {} and row["added_records"] == {}
    assert row["stock_edits"]
    assert {edit["module"] for edit in row["stock_edits"]} == {"item.fields" if kind == "fields" else "texture.replace"}
    assert {"no-new-item", "existing-content-edits"} <= {
        reason["code"] for reason in row["isolated_new_item"]["reasons"]}
    assert files_in(root) == before


def test_package_metadata_cannot_grant_isolation_or_supply_resource_proof(tmp_path):
    _, package = authored(tmp_path / "author")
    meta = deepcopy(migrate_v1(package).manifest)
    meta["metadata"] = {"isolated_new_item": True, "backend": "native",
                        "resource_graph": {"complete": True, "borrowed_paths": []}}
    forged = read_v2(meta, package.blobs)
    setup_game(tmp_path / "recipient")
    report = json_report([package_bytes(forged)], tmp_path / "recipient/game")
    row, = report["packages"]
    assert row["backend"] == "virtual" and row["shared_file_composition"]
    assert not row["isolated_new_item"]["admitted"]
    assert row["resource_graph"] != meta["metadata"]["resource_graph"]
    assert row["content_sha256"] == forged.digest


def test_package_links_remain_visible_as_exact_provider_dependencies(tmp_path):
    from tests.test_independent_package_links import pair

    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / "recipient")
    report = json_report([package_bytes(consumer), package_bytes(provider)], tmp_path / "recipient/game")
    rows = {row["identity"]: row for row in report["packages"]}
    links = rows[consumer.identity]["package_dependencies"]
    assert links["packages"] == [{"identity": provider.identity, "release": "v1", "content": provider.digest}]
    assert links["references"][0]["package"] == provider.identity
    assert "package-dependency" in {
        reason["code"] for reason in rows[consumer.identity]["isolated_new_item"]["reasons"]}
    assert not rows[provider.identity]["package_dependencies"]["packages"]


def test_strict_inspection_returns_refusal_without_publishing(tmp_path, capsys):
    from scripts.inspect_cditem_isolation import main

    _, package = authored(tmp_path / "author")
    setup_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    selected = tmp_path / "selected.cditem"
    selected.write_bytes(package_bytes(package))
    before = files_in(root)
    assert main(["--game-root", str(root), "--require-isolated", str(selected)]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["packages"][0]["identity"] == package.identity
    assert not report["published"] and not report["isolated_new_item_admitted"]
    assert files_in(root) == before


def test_regular_resolution_does_not_run_optional_diagnostic_work(tmp_path, monkeypatch):
    from cdmw.services import independent_item_isolation as owner
    from cdmw.services.independent_item_install import resolve_items
    from tests.test_independent_item_fields import field_package

    _, snapshot, _ = setup_game(tmp_path)
    package = field_package(snapshot)
    def unexpected(*args, **kwargs):
        raise AssertionError("Optional isolation inspection ran during ordinary resolution.")
    monkeypatch.setattr(owner, "assess_contribution", unexpected)
    resolved = resolve_items([package_bytes(package)], tmp_path / "game")
    assert resolved.contributions and resolved.isolation_assessments == ()


def test_hybrid_module_report_preserves_both_new_identity_and_stock_intent(tmp_path):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.domain.archives.iteminfo_composition import rows_of
    from cdmw.services.new_item_service import NewItemService
    from tests.test_archive_overlay_manager import shop_spec
    from tests.test_iteminfo_operations import assignment
    from tests.test_iteminfo_row import build_row
    from tests.test_new_item_service import build_package, _read, _table4

    _, source, entries = setup_game(tmp_path / "source")
    files = {entry.path: source.payload(entry.path) for entry in entries}
    body = source.iteminfo.payload_entry.path
    header = source.iteminfo.header_entry.path
    stock = build_row(key=992000, string_key="UnrelatedStock")
    files[body], files[header] = _table4([*rows_of(files[body], files[header]).items(), (992000, stock)])
    root = tmp_path / "game"
    imported = parse_archive_pamt(build_package(root, files))
    (root / "meta/0.pathc").write_bytes((tmp_path / "source/game/meta/0.pathc").read_bytes())
    service = NewItemService()
    snapshot = service.build_snapshot(imported, read_entry=_read)
    original = from_plan(service.plan(shop_spec("Hybrid"), snapshot, capture_independent=True), uuid4().hex)
    meta = deepcopy(migrate_v1(original).manifest)
    meta["requires"]["item.fields"] = 1
    meta["modules"].append({"id": "edits", "type": "item.fields", "version": 1, "required": True,
                            "data": {"operations": [assignment(stock, value=13)]}})
    package = read_v2(meta, original.blobs)
    before = files_in(root)
    row, = json_report([package_bytes(package)], root)["packages"]
    assert row["contribution_class"] == "mixed"
    assert row["proposed_bindings"]["iteminfo"]["item"] != 992000
    assert row["stock_edits"][0]["record"] == 992000
    assert row["stock_edits"][0]["value"] == 13
    assert not row["isolated_new_item"]["admitted"]
    assert files_in(root) == before
