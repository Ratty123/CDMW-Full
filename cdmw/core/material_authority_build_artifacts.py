"""Pure synchronization of acknowledged Material Authority build artifacts."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path


def _normalized_material(value: object) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _normalized_channel(value: object) -> str:
    token = str(value or "").strip().casefold()
    if token in {"material", "mask", "detail_mask"}:
        return "material_mask"
    if token in {"albedo", "diffuse"}:
        return "base"
    return token


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _canonical_group_values(group: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    height_scale = _finite_float(group.get("height_scale"))
    if height_scale is not None and height_scale > 0.0:
        values["height_scale"] = max(0.0, min(1.0, height_scale))
    role = str(group.get("material_role", "") or "").strip().casefold()
    if role not in {"emissive", "glow"}:
        return values
    intensity = _finite_float(group.get("emissive_intensity"))
    if intensity is None:
        raise ValueError("Canonical emissive Material Authority state is missing its intensity.")
    raw_color = group.get("emissive_color", (1.0, 1.0, 1.0))
    if not isinstance(raw_color, Sequence) or isinstance(raw_color, (str, bytes)) or len(raw_color) < 3:
        raise ValueError("Canonical emissive Material Authority state has an invalid color.")
    color = tuple(
        max(0.0, min(1.0, _finite_float(component) if _finite_float(component) is not None else 1.0))
        for component in raw_color[:3]
    )
    values["emissive_intensity"] = max(0.0, min(20.0, intensity))
    values["emissive_color"] = color
    return values


def _group_source_materials(
    group: Mapping[str, object],
    bindings: Sequence[Mapping[str, object]],
) -> set[str]:
    indices = {
        int(index)
        for index in tuple(group.get("source_submesh_indices", ()) or ())
        if isinstance(index, int) or str(index).strip().lstrip("-").isdigit()
    }
    sources: set[str] = set()
    for binding in bindings:
        affected = {
            int(index)
            for index in tuple(binding.get("affected_submeshes", ()) or ())
            if isinstance(index, int) or str(index).strip().lstrip("-").isdigit()
        }
        if indices and affected and not indices.intersection(affected):
            continue
        material = str(binding.get("material_name", "") or "").strip()
        if material:
            sources.add(material)
    return sources


def _canonical_sidecar_targets(
    bindings: Sequence[Mapping[str, object]],
    mappings: Sequence[object],
    parameter_groups: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    targets_by_source: dict[str, dict[str, str]] = {}
    for mapping in mappings:
        source = str(getattr(mapping, "source_material_name", "") or "").strip()
        target = str(getattr(mapping, "target_material_name", "") or "").strip()
        if source and target:
            targets_by_source.setdefault(_normalized_material(source), {})[
                _normalized_material(target)
            ] = target
    result: dict[str, dict[str, object]] = {}
    for group in parameter_groups:
        values = _canonical_group_values(group)
        if not values:
            continue
        sources = _group_source_materials(group, bindings)
        targets = {
            target_key: target_name
            for source in sources
            for target_key, target_name in targets_by_source.get(_normalized_material(source), {}).items()
        }
        if not targets and len(targets_by_source) == 1:
            targets = dict(next(iter(targets_by_source.values())))
        if not targets:
            raise ValueError("Canonical Material Authority parameters have no Build Mod material target.")
        for target_key, target_name in targets.items():
            current = result.setdefault(target_key, {"material_name": target_name})
            for key, value in values.items():
                if key in current and current[key] != value:
                    raise ValueError(
                        f"Canonical Material Authority parameters conflict on shared target material {target_name}."
                    )
                current[key] = value
    return result


def _parameter_name(block: str) -> str:
    match = re.search(
        r'\b(?:_name|Name|name|StringItemID)="([^"]*)"',
        block,
        flags=re.IGNORECASE,
    )
    return str(match.group(1) if match else "").strip().casefold()


def _replace_parameter_value(block: str, value: str) -> str:
    replaced, count = re.subn(
        r'(\b(?:_value|Value|value)=")([^"]*)(")',
        rf"\g<1>{value}\3",
        block,
        count=1,
        flags=re.IGNORECASE,
    )
    if count:
        return replaced
    return re.sub(r"\s*/>$", f' _value="{value}"/>', block, count=1)


def _color_hex(value: object) -> str:
    color = tuple(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    channels = [int(round(max(0.0, min(1.0, float(component))) * 255.0)) for component in color[:3]]
    if len(channels) != 3:
        channels = [255, 255, 255]
    return "#" + "".join(f"{channel:02X}" for channel in channels) + "FF"


def _patch_wrapper_parameters(body: str, expected: Mapping[str, object]) -> tuple[str, set[str]]:
    changed: set[str] = set()

    def patch_blocks(tag: str, names: set[str], key: str, value: str) -> None:
        nonlocal body

        def patch(match: re.Match[str]) -> str:
            if _parameter_name(match.group(0)) not in names:
                return match.group(0)
            changed.add(key)
            return _replace_parameter_value(match.group(0), value)

        body = re.sub(
            rf"<MaterialParameter{tag}\b[^>]*/>",
            patch,
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )

    if "emissive_intensity" in expected:
        patch_blocks(
            "Float",
            {"_emissiveintensity"},
            "emissive_intensity",
            f'{float(expected["emissive_intensity"]):.6f}',
        )
        patch_blocks(
            "Color",
            {"_emissivecolor"},
            "emissive_color",
            _color_hex(expected.get("emissive_color")),
        )
    if "height_scale" in expected:
        patch_blocks(
            "Float",
            {"_screenspacedisplacementscale", "_detailscreenspacedisplacementscale"},
            "height_scale",
            f'{float(expected["height_scale"]):.6f}',
        )
    return body, changed


def _patch_sidecar_text(
    text: str,
    targets: Mapping[str, Mapping[str, object]],
) -> tuple[str, dict[str, set[str]]]:
    patched_keys: dict[str, set[str]] = {}
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)"
        r"(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def patch(match: re.Match[str]) -> str:
        name_match = re.search(r'\b_subMeshName="([^"]*)"', match.group("attrs"), flags=re.IGNORECASE)
        target_key = _normalized_material(name_match.group(1) if name_match else "")
        expected = targets.get(target_key)
        if expected is None:
            return match.group(0)
        body, changed = _patch_wrapper_parameters(match.group("body"), expected)
        patched_keys.setdefault(target_key, set()).update(changed)
        return f"{match.group(1)}{body}{match.group(5)}"

    return wrapper_pattern.sub(patch, text), patched_keys


def _parameter_value(block: str) -> str:
    match = re.search(
        r'\b(?:_value|Value|value)="([^"]*)"',
        block,
        flags=re.IGNORECASE,
    )
    return str(match.group(1) if match else "").strip()


def _read_wrapper_parameters(body: str, expected: Mapping[str, object]) -> set[str]:
    float_values: dict[str, list[float]] = {}
    for block in re.findall(
        r"<MaterialParameterFloat\b[^>]*/>",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        value = _finite_float(_parameter_value(block))
        if value is not None:
            float_values.setdefault(_parameter_name(block), []).append(value)
    color_values = {
        _parameter_name(block): _parameter_value(block).upper()
        for block in re.findall(
            r"<MaterialParameterColor\b[^>]*/>",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
    }
    observed: set[str] = set()
    if "emissive_intensity" in expected:
        values = float_values.get("_emissiveintensity", ())
        if values and all(abs(value - float(expected["emissive_intensity"])) <= 0.0000005 for value in values):
            observed.add("emissive_intensity")
        if color_values.get("_emissivecolor") == _color_hex(expected.get("emissive_color")):
            observed.add("emissive_color")
    if "height_scale" in expected:
        values = (
            float_values.get("_screenspacedisplacementscale", [])
            + float_values.get("_detailscreenspacedisplacementscale", [])
        )
        if values and all(abs(value - float(expected["height_scale"])) <= 0.0000005 for value in values):
            observed.add("height_scale")
    return observed


def _read_sidecar_text(
    text: str,
    targets: Mapping[str, Mapping[str, object]],
) -> dict[str, set[str]]:
    observed: dict[str, set[str]] = {}
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>"
        r"(?P<body>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in wrapper_pattern.finditer(text):
        name_match = re.search(r'\b_subMeshName="([^"]*)"', match.group("attrs"), flags=re.IGNORECASE)
        target_key = _normalized_material(name_match.group(1) if name_match else "")
        expected = targets.get(target_key)
        if expected is not None:
            observed.setdefault(target_key, set()).update(
                _read_wrapper_parameters(match.group("body"), expected)
            )
    return observed


def _synchronize_material_authority_sidecars(
    payloads: Sequence[object],
    bindings: Sequence[Mapping[str, object]],
    mappings: Sequence[object],
    parameter_groups: Sequence[Mapping[str, object]],
    *,
    fingerprint: str,
) -> tuple[dict[str, object], ...]:
    targets = _canonical_sidecar_targets(bindings, mappings, parameter_groups)
    if not targets:
        return ()
    observed: dict[str, set[str]] = {key: set() for key in targets}
    records: list[dict[str, object]] = []
    for payload in payloads:
        if str(getattr(payload, "kind", "") or "") != "sidecar_generated":
            continue
        original = bytes(getattr(payload, "payload_data", b"") or b"")
        has_bom = original.startswith(b"\xef\xbb\xbf")
        text = original.decode("utf-8-sig")
        patched, changed = _patch_sidecar_text(text, targets)
        if not changed:
            continue
        for target_key, keys in changed.items():
            observed.setdefault(target_key, set()).update(keys)
        data = patched.encode("utf-8")
        if has_bom:
            data = b"\xef\xbb\xbf" + data
        payload.payload_data = data
        payload.note = (
            f"{str(getattr(payload, 'note', '') or '').strip()} "
            f"Material Authority canonical sidecar {fingerprint[:12]}"
        ).strip()
        readback_text = bytes(payload.payload_data).decode("utf-8-sig")
        readback = _read_sidecar_text(readback_text, targets)
        for target_key, keys in readback.items():
            observed.setdefault(target_key, set()).update(keys)
        records.append(
            {
                "kind": "sidecar_parameters",
                "target_path": str(getattr(payload, "target_path", "") or ""),
                "content_sha256": _sha256_bytes(bytes(payload.payload_data)),
                "byte_count": len(bytes(payload.payload_data)),
                "fingerprint": fingerprint,
            }
        )
    for target_key, expected in targets.items():
        required = {key for key in expected if key != "material_name"}
        missing = required - observed.get(target_key, set())
        if missing:
            material_name = str(expected.get("material_name", target_key) or target_key)
            raise ValueError(
                f"Generated Material Authority sidecar cannot represent {material_name}: "
                + ", ".join(sorted(missing))
                + "."
            )
    if not records:
        raise ValueError("Canonical Material Authority parameters have no generated sidecar readback.")
    return tuple(records)


def synchronize_material_authority_build_payloads(
    payloads: Sequence[object],
    report: object,
    bindings: Sequence[Mapping[str, object]],
    *,
    fingerprint: object,
    parameter_groups: Sequence[Mapping[str, object]] = (),
) -> tuple[dict[str, object], ...]:
    """Replace generated texture payload bytes with the exact acknowledged DDS bytes."""

    expected_fingerprint = str(fingerprint or "").strip()
    if not expected_fingerprint:
        raise ValueError("Material Authority build is missing its acknowledged fingerprint.")
    texture_payloads = {
        str(getattr(payload, "target_path", "") or "").replace("\\", "/").casefold(): payload
        for payload in payloads
        if str(getattr(payload, "kind", "") or "") == "texture_generated"
    }
    mappings = tuple(getattr(report, "slot_mappings", ()) or ())
    records: list[dict[str, object]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping) or bool(binding.get("remove", False)):
            continue
        source = Path(str(binding.get("source_dds_path", binding.get("path", "")) or "")).expanduser()
        expected_hash = str(binding.get("content_sha256", "") or "").strip().casefold()
        if source.suffix.casefold() != ".dds" or not source.is_file() or not expected_hash:
            raise ValueError("Resolved Material Authority binding is missing a readable hashed DDS artifact.")
        data = source.read_bytes()
        actual_hash = _sha256_bytes(data)
        if actual_hash != expected_hash:
            raise ValueError("Resolved Material Authority DDS hash changed before Build Mod.")
        material = _normalized_material(binding.get("material_name", ""))
        channel = _normalized_channel(binding.get("channel", ""))
        candidates: list[object] = []
        for mapping in mappings:
            if _normalized_channel(getattr(mapping, "slot_kind", "")) != channel:
                continue
            source_material = _normalized_material(getattr(mapping, "source_material_name", ""))
            target_material = _normalized_material(getattr(mapping, "target_material_name", ""))
            if material and material not in {source_material, target_material}:
                continue
            payload = texture_payloads.get(
                str(getattr(mapping, "output_texture_path", "") or "").replace("\\", "/").casefold()
            )
            if payload is not None and payload not in candidates:
                candidates.append(payload)
        if not candidates:
            channel_mappings = [
                mapping
                for mapping in mappings
                if _normalized_channel(getattr(mapping, "slot_kind", "")) == channel
            ]
            if len(channel_mappings) == 1:
                payload = texture_payloads.get(
                    str(getattr(channel_mappings[0], "output_texture_path", "") or "")
                    .replace("\\", "/")
                    .casefold()
                )
                if payload is not None:
                    candidates.append(payload)
        if not candidates:
            raise ValueError(
                f"Resolved Material Authority artifact has no Build Mod target: "
                f"{binding.get('material_name', '')} {channel}."
            )
        for payload in candidates:
            payload.payload_data = data
            payload.source_path = source
            payload.note = (
                f"Material Authority exact artifact {expected_hash[:12]} "
                f"({binding.get('material_name', '')} {channel})"
            )
            readback_hash = _sha256_bytes(bytes(payload.payload_data))
            if readback_hash != expected_hash:
                raise ValueError("Build Mod Material Authority DDS failed byte-for-byte readback.")
            records.append(
                {
                    "target_path": str(getattr(payload, "target_path", "") or ""),
                    "material_name": str(binding.get("material_name", "") or ""),
                    "channel": channel,
                    "content_sha256": expected_hash,
                    "byte_count": len(data),
                    "fingerprint": expected_fingerprint,
                }
            )
    if not records:
        raise ValueError("Material Authority build has no exact DDS artifacts to publish.")
    records.extend(
        _synchronize_material_authority_sidecars(
            payloads,
            bindings,
            mappings,
            parameter_groups,
            fingerprint=expected_fingerprint,
        )
    )
    return tuple(records)


__all__ = ["synchronize_material_authority_build_payloads"]
