"""Cached lazy service boundary for HKX edit and corpus export workflows."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    name: ("cdmw.core.archive_hkx", name)
    for name in (
        "HkxGeometryPatchResult",
        "apply_hkx_editable_geometry_json",
        "apply_hkx_editable_geometry_xml",
        "build_hkx_descriptor_hint_from_xml_text",
        "build_hkx_editable_geometry_json",
        "build_hkx_editable_geometry_xml",
        "build_hkx_havok_xml_view_xml",
    )
}
_EXPORTS.update(
    {
        name: ("cdmw.core.archive_hkx_corpus_report", name)
        for name in ("build_hkx_converter_corpus_csv", "build_hkx_converter_corpus_json")
    }
)
__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
