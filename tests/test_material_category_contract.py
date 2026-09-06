"""The material category vocabulary must agree across Python, C#, HLSL, and Rust.

The same decision is represented three times: Python emits a category string,
``NetMaterialSet.Resident.cs`` maps it to a float code, and the pixel shader
decodes that float into per-category booleans. Drift between them is silent --
an unmapped string becomes code 0 and the surface loses its response with no
error anywhere. These tests parse the real C# and HLSL sources rather than a
generated copy, so a hand edit to either side fails here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


from cdmw.rendering.material_category_contract import MATERIAL_CATEGORIES, MATERIAL_CATEGORY_CODES, MATERIAL_CATEGORY_UNCLASSIFIED, material_category_code, material_category_for_code


ROOT = Path(__file__).resolve().parents[1]
RESIDENT_CS = ROOT / "tools/dotnet_mesh_editor_experiment/NetMaterialSet.Resident.cs"
SHADER_HLSL = ROOT / "tools/dotnet_mesh_editor_experiment/D3D11MaterialShaders.hlsl"
RUST_SESSION = ROOT / "tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_session.rs"
PYTHON_PRODUCER = ROOT / "cdmw/rendering/native_preview_material_contract.py"
PRODUCER_FUNCTION = "_resolved_batch_material_category"


def _csharp_category_codes() -> dict[str, int]:
    """Parse the string -> float mapping out of MaterialCategoryCodeForSubmesh."""
    source = RESIDENT_CS.read_text(encoding="utf-8")
    start = source.index("public float MaterialCategoryCodeForSubmesh")
    body = source[start : source.index("\n    }", start)]
    pairs = re.findall(
        r'category\.Equals\("([a-z]+)",\s*StringComparison\.OrdinalIgnoreCase\)\)\s*'
        r"return\s+([0-9]+)\.0f;",
        body,
    )
    assert pairs, "could not parse any category mapping out of the C# source"
    return {name: int(code) for name, code in pairs}


def _csharp_fallback_code() -> int:
    source = RESIDENT_CS.read_text(encoding="utf-8")
    start = source.index("public float MaterialCategoryCodeForSubmesh")
    body = source[start : source.index("\n    }", start)]
    fallback = re.search(r"return\s+([0-9]+)\.0f;\s*$", body.rstrip())
    assert fallback is not None, "C# category mapping has no fallback return"
    return int(fallback.group(1))


def _hlsl_category_ranges() -> dict[str, tuple[float, float]]:
    """Parse `x > lo && x < hi` category decodes out of the shader."""
    source = SHADER_HLSL.read_text(encoding="utf-8")
    matches = re.findall(
        r"bool\s+(?:source)?[Cc]ategory([A-Za-z]+)\s*=\s*"
        r"materialCategoryCode\s*>\s*([0-9.]+)f\s*&&\s*"
        r"materialCategoryCode\s*<\s*([0-9.]+)f",
        source,
    )
    assert matches, "could not parse any category range out of the HLSL source"
    return {
        name.casefold(): (float(low), float(high)) for name, low, high in matches
    }


def _rust_category_codes() -> dict[str, int]:
    source = RUST_SESSION.read_text(encoding="utf-8")
    start = source.index("fn material_category_code")
    body = source[start : source.index("\n}", start)]
    pairs = re.findall(r'"([a-z]+)"\s*=>\s*Some\(([0-9]+)\)', body)
    assert pairs, "could not parse any category mapping out of the source"
    return {name: int(code) for name, code in pairs}


def _python_producer_categories() -> set[str]:
    """Every string literal the authoritative classifier can return."""
    tree = ast.parse(PYTHON_PRODUCER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == PRODUCER_FUNCTION:
            found: set[str] = set()
            for statement in ast.walk(node):
                if isinstance(statement, ast.Return) and statement.value is not None:
                    for constant in ast.walk(statement.value):
                        if isinstance(constant, ast.Constant) and isinstance(
                            constant.value, str
                        ):
                            found.add(constant.value)
            return found
    raise AssertionError(f"{PRODUCER_FUNCTION} is no longer in {PYTHON_PRODUCER.name}")




def test_rust_mapping_matches_the_contract_exactly() -> None:
    assert _rust_category_codes() == dict(MATERIAL_CATEGORY_CODES)










def test_python_producer_emits_only_contract_categories() -> None:
    # This is the hole the contract exists to close: adding a category here
    # previously failed nowhere and silently degraded to code 0.
    unknown = sorted(_python_producer_categories() - set(MATERIAL_CATEGORIES))

    assert not unknown, (
        f"{PRODUCER_FUNCTION} can emit {unknown}, which the contract does not "
        "define, so the renderer would receive code 0 for them"
    )


def test_contract_codes_are_unique_and_contiguous() -> None:
    codes = list(MATERIAL_CATEGORY_CODES.values())

    assert len(set(codes)) == len(codes), "duplicate category code"
    assert codes == sorted(codes), "categories are not declared in code order"
    assert codes == list(range(len(codes))), "codes are not contiguous from zero"


def test_lookup_is_lenient_the_same_way_the_dotnet_side_is() -> None:
    assert material_category_code("  Metal  ") == MATERIAL_CATEGORY_CODES["metal"]
    assert material_category_code("METAL") == MATERIAL_CATEGORY_CODES["metal"]
    for absent in ("", None, "not_a_category"):
        assert material_category_code(absent) == 0
    assert material_category_for_code(2) == "leather"
    assert material_category_for_code(99) == MATERIAL_CATEGORY_UNCLASSIFIED
