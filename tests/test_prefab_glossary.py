"""Guards for the prefab field glossary.

The glossary exists so the inspector never shows a raw ``_camelCase`` name. Its
value is entirely in the mapping, so these tests check the mapping's shape and
the fallback, not that any particular wording survives forever.
"""

from __future__ import annotations

import pytest

from cdmw.domain.archives.prefab_glossary import (
    _FIELDS,
    asset_role,
    describe_component,
    describe_field,
    describe_fields,
    humanise_declared_name,
    is_asset_path,
    value_kind_hint,
)


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("_skinnedMeshFile", "Mesh"),
        ("_socketFileName", "Socket data"),
        ("_shrinkMaskDistance", "Shrink distance"),
        ("_displayName", "Display name"),
        ("_diffuseTexture", "Base texture"),
        ("_ignoreCollisionMasks", "Ignored collision layers"),
        ("_fadeInTime", "Fade-in time"),
    ],
)
def test_curated_fields_read_as_prose(declared: str, expected: str) -> None:
    assert describe_field(declared).label == expected


def test_engine_typos_are_corrected_in_the_label() -> None:
    """The engine spells it ``_smootingDistance``; readers should not have to."""
    assert describe_field("_smootingDistance").label == "Smoothing distance"


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("_someUnknownThing", "Some unknown thing"),
        ("_vertices", "Vertices"),
        ("_hasExitTime", "Has exit time"),
        ("_useHDR", "Use HDR"),
        ("", ""),
    ],
)
def test_unknown_fields_fall_back_to_readable_text(declared: str, expected: str) -> None:
    assert humanise_declared_name(declared) == expected
    assert describe_field(declared).label == expected


def test_every_curated_entry_has_a_label() -> None:
    assert _FIELDS, "glossary must not be empty"
    for name, meaning in _FIELDS.items():
        assert meaning.label.strip(), f"{name} has no label"
        assert not meaning.label.startswith("_"), f"{name} still shows a declared name"


def test_describe_fields_preserves_order() -> None:
    names = ("_skinnedMeshFile", "_socketFileName", "_shrinkTag")
    assert describe_fields(names) == ("Mesh", "Socket data", "Shrink group")


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("a/b/c.pac", "Model"),
        ("a/b/c.pab", "Skeleton"),
        ("a/b/c.dds", "Texture"),
        # A .pami is an XML <StaticMeshInstance> naming a mesh and its
        # materials, not a texture -- calling it "Material" misdirects.
        ("a/b/c.pami", "Mesh instance"),
        ("a/b/c.sockets.xml", "Socket data"),
        ("a/b/c.unknownext", "File"),
        ("", "File"),
    ],
)
def test_asset_roles(path: str, role: str) -> None:
    assert asset_role(path) == role


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("character/model/a.pac", True),
        ("Pelvis_R_Socket", False),
        ("no-slash.pac", False),
        ("has/slash-but-no-dot", False),
    ],
)
def test_asset_path_detection(value: str, expected: bool) -> None:
    assert is_asset_path(value) is expected


@pytest.mark.parametrize(
    ("type_name", "kind", "expected"),
    [
        ("ReflectObjectPtr", "reference", "points at another file"),
        ("bool", "value", "on/off"),
        ("Transform", "value", "position / rotation / scale"),
        ("SceneObjectUuid", "value", "identifier"),
        ("float", "value", "number"),
    ],
)
def test_value_kind_hints(type_name: str, kind: str, expected: str) -> None:
    assert value_kind_hint(type_name, kind) == expected


def test_known_components_are_explained() -> None:
    assert "rigged mesh" in describe_component("SkinnedMeshComponent")
    assert describe_component("SomethingUnheardOf") == ""
