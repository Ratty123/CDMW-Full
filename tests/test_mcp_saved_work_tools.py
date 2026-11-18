from cdmw.services.mesh_saved_work_service import list_saved_work
from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_saved_work_combine_page import _owned_history, app, combine


def test_saved_work_names_projects_continuation_and_deletion(combine):
    page = combine.page
    client = RailClient(combine.tmp, widgets={"saved_work": page})
    state = client.ok("saved.list")
    row = next(row for row in state["rows"] if row["name"] == "Wing piece")
    continued = []
    page.continue_requested.connect(continued.append)
    client.ok("saved.change", action="continue", id=row["id"])
    assert continued[-1].display_name == "Wing piece"

    client.ok("saved.change", action="new_project", name="Rail project")
    wait_for(lambda: any(project.name == "Rail project" for project in page.projects()))
    project = next(project.project_id for project in page.projects() if project.name == "Rail project")
    client.ok("saved.change", action="rename_project", project=project, name="Renamed project")
    wait_for(lambda: any(project.name == "Renamed project" for project in page.projects()))
    client.ok("saved.change", action="rename", id=row["id"], name="Renamed wing", notes="Owned evidence", project=project)
    wait_for(lambda: any(row.display_name == "Renamed wing" for row in page.rows()))
    saved = next(row for row in list_saved_work(combine.drafts) if row.display_name == "Renamed wing")
    assert (saved.notes, saved.project_id) == ("Owned evidence", project)
    client.ok("saved.delete", action="project", project=project)
    wait_for(lambda: not page.projects())
    client.ok("saved.delete", action="entry", id=row["id"])
    wait_for(lambda: len(page.rows()) == 1)
    assert combine.wing.is_dir() and len(list_saved_work(combine.drafts)) == 1


def test_saved_work_combines_real_built_mods_and_publishes_one_row(combine):
    client = RailClient(combine.tmp, widgets={"saved_work": combine.page})
    rows = client.ok("saved.list")["rows"]
    target = combine.tmp / "combined-from-mcp"
    result = client.ok("saved.combine", ids=[row["id"] for row in rows], name="Combined", destination=str(target))
    assert result["output"]
    wait_for(lambda: len(combine.page.rows()) == 3)
    assert target.is_dir() and any(path.is_file() for path in target.rglob("*"))
    assert len(list_saved_work(combine.drafts)) == 3


def test_saved_work_adds_a_mod_folder_and_item_package_via_the_page(combine):
    from cdmw.services.independent_item_package import package_bytes
    from tests.test_independent_item_fields import field_package
    from tests.test_independent_items import setup_game
    from tests.test_mesh_build_combine import UPPER, _build

    client = RailClient(combine.tmp, widgets={"saved_work": combine.page})
    folder = _build(combine.builds, "Additional build", {UPPER: (b"third build", "0009")})
    client.ok("saved.change", action="add_folder", path=str(folder))
    wait_for(lambda: any(row.display_name == "Additional build" for row in combine.page.rows()))

    _, snapshot, _ = setup_game(combine.tmp / "package-fixture")
    path = combine.tmp / "Owned item.cdmw"
    raw = package_bytes(field_package(snapshot, value=1))
    path.write_bytes(raw)
    client.ok("saved.change", action="add_package", path=str(path))
    wait_for(lambda: any(row.package_path == path for row in combine.page.rows()))
    saved = list_saved_work(combine.drafts)
    assert any(row.display_name == "Additional build" for row in saved)
    assert any(row.package_path == path for row in saved) and path.read_bytes() == raw
