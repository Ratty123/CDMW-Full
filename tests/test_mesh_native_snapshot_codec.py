from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from cdmw.modding.mesh_native_snapshot_codec import _snapshot_metadata_value


def test_snapshot_metadata_remains_detached_and_json_safe():
    @dataclass
    class Material:
        color: tuple[float, ...]
        enabled: bool

    source = {
        "uv_sets": {0: [(0.25, 0.75), (float("nan"), float("inf"))]},
        "material": Material((0.1, 0.2, 0.3), True),
        "read_only": MappingProxyType({"path": Path("texture.dds"), "empty": None}),
    }
    captured = _snapshot_metadata_value(source)
    source["uv_sets"][0][0] = (9, 9)
    source["material"].color = (1, 1, 1)
    assert captured == {
        "uv_sets": {"0": [[0.25, 0.75], [None, None]]},
        "material": {"color": [0.1, 0.2, 0.3], "enabled": True},
        "read_only": {"path": "texture.dds", "empty": None},
    }


def test_dataclass_container_subclasses_keep_their_metadata_contract():
    @dataclass
    class NamedList(list):
        name: str

    values = NamedList("source")
    values.extend([1, 2])
    # The exact-built-in fast path must not hide a subclass's declared fields.
    assert _snapshot_metadata_value(values) == {"name": "source"}
