"""The experimental `speed.` tools against a fake archive index."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cdmw.mcp import speed_tools as module
from cdmw.mcp.errors import ToolError
from cdmw.mcp.names import OUTPUT, READ
from cdmw.mcp.schema import validate_arguments
from cdmw.mcp.server import ToolCall
from cdmw.services.action_chart_edit_service import chart_archive_index, read_chart_mod
from tests.prefab_speed_builder import build_speed_prefab
from tests.test_action_chart_binary import CLIPS, chart_bytes, descriptor_bytes
from tests.test_action_chart_editor import BASIC, DESCRIPTION, PATH, accelerator, stored  # noqa: F401 - fixtures

ATTACK, IDLE = CLIPS
PREFAB = "object/prefab/wind_crate.prefab"
TOOLS = {tool.name: tool for tool in module.speed_tools()}


@pytest.fixture
def speed(stored, tmp_path, monkeypatch):
    prefab = build_speed_prefab([("WindComponent", [("_windSpeedAccelerationScale", "float", 2.0)])])
    entries = [stored(PATH, chart_bytes()), stored(BASIC, chart_bytes()), stored(DESCRIPTION, descriptor_bytes()),
               stored(PREFAB, prefab)]
    root = tmp_path / "game-root"
    root.mkdir()
    index = chart_archive_index(root, scan=lambda _root: entries)
    monkeypatch.setattr(module, "_index", lambda context: index)
    monkeypatch.setattr(module, "_read", lambda entry: entry.paz_file.read_bytes())
    context = SimpleNamespace(game_folder=lambda: str(root))

    def call(name, **arguments):
        tool = TOOLS[name]
        return tool.handler(ToolCall(tool, validate_arguments(arguments, tool.input_schema), context))

    call.index = index
    return call


def test_every_tool_is_experimental_in_the_speed_family_with_the_right_class():
    assert set(TOOLS) == {"speed.sets", "speed.set", "speed.preview", "speed.export", "speed.prefab_search",
                          "speed.prefab_values", "speed.prefab_export", "speed.table_rows", "speed.table_export"}
    for tool in TOOLS.values():
        assert tool.family == "speed" and "Experimental" in tool.description
        assert tool.input_schema["type"] == "object" and tool.input_schema["additionalProperties"] is False
        assert tool.effect == (OUTPUT if tool.name.endswith("export") else READ)
    assert TOOLS["speed.export"].output_folders == ("folder",)
    assert TOOLS["speed.prefab_export"].output_paths == ("package",)


def test_sets_and_one_set(speed):
    sets = speed("speed.sets")["sets"]
    assert {(row["character"], row["path"]) for row in sets} == {("Kliff", PATH), ("Kliff", BASIC)}
    one = speed("speed.set", path=PATH)
    assert one["label"] == "Sword" and [m["kind"] for m in one["moves"]] == ["attack", "idle"]
    assert one["factors"] == {"set": 1.0, "kinds": {}, "moves": {}}


def test_preview_counts_changes_and_writes_nothing(speed):
    result = speed("speed.preview", path=PATH, factors={"set": 2.0, "kinds": {"attack": 2.0}})
    assert result["written"] is False and result["changed_values"] == 2
    assert result["charts"][0]["kinds"][0]["after"] == [2.0, 2.0]


def test_export_refuses_a_bad_factor_and_an_unknown_set(speed, tmp_path):
    folder = tmp_path / "mods"
    folder.mkdir()
    with pytest.raises(ToolError):
        speed("speed.export", path=PATH, factors={"set": 9.0}, folder=str(folder), title="Fast")
    with pytest.raises(ToolError, match="Unknown move kind"):
        speed("speed.export", path=PATH, factors={"kinds": {"swim": 2.0}}, folder=str(folder), title="Fast")
    with pytest.raises(ToolError, match="not in the game archives"):
        speed("speed.export", path="actionchart/bin__/upperaction/missing.paac", factors={"set": 2.0},
              folder=str(folder), title="Fast")


def test_export_writes_the_mod_and_set_reads_its_factors_back(speed, tmp_path, accelerator):
    folder = tmp_path / "mods"
    folder.mkdir()
    result = speed("speed.export", path=PATH, factors={"moves": {ATTACK: 2.0}}, folder=str(folder), title="Fast",
                   linked=False)
    assert result["charts"] == [PATH] and result["changed_values"] == 1
    assert set(read_chart_mod(result["folder"]).charts) == {PATH}
    again = speed("speed.set", path=PATH, mod_folder=result["folder"])
    assert again["mod"] == "Fast" and again["moves"][0]["factor"] == 2.0


def test_prefab_tools_find_read_and_package(speed, tmp_path, monkeypatch):
    hits = speed("speed.prefab_search")["prefabs"]
    assert [hit["path"] for hit in hits] == [PREFAB] and hits[0]["categories"] == ["moving"]
    assert speed("speed.prefab_search", category="cameras")["prefabs"] == []
    values = speed("speed.prefab_values", path=PREFAB)["values"]
    assert [(v["member"], v["value"]) for v in values] == [("_windSpeedAccelerationScale", 2.0)]

    written = {}
    monkeypatch.setattr("cdmw.services.independent_prefab_authoring.prepare_prefab_package",
                        lambda root, path, patched, **kw: written.update(path=path, data=patched)
                        or SimpleNamespace(lines=("ok",)))
    monkeypatch.setattr("cdmw.services.independent_prefab_authoring.write_prefab_package",
                        lambda review, destination, **kw: written.update(destination=destination))
    result = speed("speed.prefab_export", path=PREFAB, package=str(tmp_path / "fast.cdmw"), factor=2.0)
    assert result["edits"] == 1 and written["path"] == PREFAB
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.services.prefab_speed_service import speed_values

    assert speed_values(decode_prefab_binary(written["data"]))[0].value == 4.0
    with pytest.raises(ToolError, match="must end in"):
        speed("speed.prefab_export", path=PREFAB, package=str(tmp_path / "fast.zip"), factor=2.0)
    with pytest.raises(ToolError, match="Give either"):
        speed("speed.prefab_export", path=PREFAB, package=str(tmp_path / "other.cdmw"))


def test_table_export_refuses_fields_that_are_not_speeds(speed, tmp_path):
    folder = tmp_path / "mods"
    folder.mkdir()
    with pytest.raises(ToolError, match="not a game table speed field"):
        speed("speed.table_export", edits=[{"table": "gimmickinfo", "key": 1, "target": "_key", "value": 2}],
              folder=str(folder), title="Fast")
