from __future__ import annotations

from pathlib import Path

from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT
from tests.test_architecture_size_ratchets import _brace_function_spans


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "native" / "cd_hkx" / "src"


def test_cd_hkx_library_is_a_thin_normal_module_facade() -> None:
    facade = (SOURCE_ROOT / "lib.rs").read_text(encoding="utf-8")

    assert len(facade.splitlines()) <= 100
    assert "include!(" not in facade
    for owner in (
        "parsing",
        "fixup_decode",
        "layout",
        "graph",
        "evidence",
        "schema",
        "editing",
        "no_edit",
        "json_summary",
    ):
        assert f"mod {owner};" in facade


def test_cd_hkx_owner_files_and_functions_stay_bounded() -> None:
    owners = tuple(
        path
        for path in SOURCE_ROOT.rglob("*.rs")
        if path.name not in {"lib.rs", "main.rs"}
    )

    assert len(owners) >= 30
    for owner in owners:
        source = owner.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, owner
        assert "include!(" not in source, owner
        for key, span in _brace_function_spans(owner).items():
            assert span <= 150, f"{key}: {span} lines"
