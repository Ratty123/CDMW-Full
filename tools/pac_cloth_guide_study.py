"""Inspect loose, decoded PAC guide meshes without modifying the input files.

Run with one or more .pac paths. JSON on stdout includes source hashes, guide
bounds, topology, packed skin bindings, particle initialization and raw channels
with byte-range provenance. Active materials and runtime overrides are not assumed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdmw.modding.pac_cloth_guides import (
    decode_pac_cloth_guides, inspect_guide_attachment_candidates, inspect_guide_constraint_geometry,
    inspect_guide_particle_initialization, inspect_guide_profile_admission, inspect_guide_topology,
)
from cdmw.core.pbd_cloth import _parse_xml, parse_pbd_material_settings
from cdmw.models import PbdMaterialSettings
from cdmw.modding.pac_cloth_preparation import prepare_guide_cloth_attachments
from cdmw.modding.pac_cloth_skinning import guide_runtime_blend_factor, inspect_render_cloth_bindings


def inspect_pac(data: bytes, *, path: str = "", material: PbdMaterialSettings | None = None) -> dict:
    result = {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    try:
        guides = decode_pac_cloth_guides(data)
    except ValueError as exc:
        return {**result, "status": "unavailable", "reason": str(exc)}
    if guides is None:
        return {**result, "status": "absent", "reason": "No PAC guide-section flag; other physics may still be present."}
    payload = asdict(guides)
    payload["channel_a"] = list(guides.channel_a)
    payload["channel_b"] = list(guides.channel_b)
    material_inputs = {} if material is None else {
        "material_mass": material.mass,
        "use_vertex_alpha_position_blending": material.use_vertex_alpha_position_blending,
    }
    result = {**result, "status": "decoded", "vertex_count": len(guides.vertices),
            "triangle_count": len(guides.triangles), "guides": payload,
            "profile_resource_prerequisites": inspect_guide_profile_admission(guides.metadata_flags, len(guides.vertices)),
            "topology_evidence": inspect_guide_topology(guides),
            "particle_initialization": inspect_guide_particle_initialization(guides, **material_inputs),
            "constraint_geometry": inspect_guide_constraint_geometry(guides),
            "cloth_attachment_candidates": inspect_guide_attachment_candidates(guides),
            "render_bindings": inspect_render_cloth_bindings(data, guides),
            "limitations": "Particle channels describe initialization, not final runtime motion. Inverse-mass factors require the material Mass; both vertex-alpha blend modes are shown because the active material is unresolved. Dynamic-fix groups require runtime activation. Constraint rest geometry uses CPU coordinates before skinning; active area/bending modes, collisions and runtime overrides are not simulated."}
    if material is not None:
        result["supplied_material"] = {
            "path": material.material_path,
            "use_rotation_correction": material.use_rotation_correction,
            "underwater_guide_mesh_vertex_weight_coefficient": material.underwater_guide_mesh_vertex_weight_coefficient,
            "dynamic_underwater_guide_matrix_factor": guide_runtime_blend_factor(
                inverse_mass=1.0, particle_flags=0x80,
                underwater_coefficient=material.underwater_guide_mesh_vertex_weight_coefficient,
            ),
            "limitations": "The supplied profile is a calculation input, not proof of the active in-game material. The underwater factor requires a dynamic particle with flag 0x80 and without override 0x800000. Initial position blends precede long-range attachment preparation and runtime updates.",
            "cloth_mode_preparation_without_auto_weighting": {
                scope: prepare_guide_cloth_attachments(
                    guides, separate_components=separate,
                    use_vertex_alpha_position_blending=material.use_vertex_alpha_position_blending,
                    auto_weighting_enabled=False,
                    auto_weighting_exponential_base=material.auto_weighting_exponential_base,
                    auto_weighting_input_ratio_shift=material.auto_weighting_input_ratio_shift,
                ) for scope, separate in (("by_connected_component", True), ("whole_mesh", False))
            },
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pac", type=Path, nargs="+", help="Loose decompressed .pac files, read-only.")
    parser.add_argument("--material", type=Path, help="Optional loose PBD material XML used for initial-value calculations on every input PAC.")
    args = parser.parse_args(argv)
    material = None
    material_source = None
    if args.material is not None:
        try:
            raw_material = args.material.read_bytes()
            material_text = raw_material.decode("utf-8-sig")
            if _parse_xml(material_text) is None:
                raise ValueError("The supplied PBD material XML is malformed.")
            material = parse_pbd_material_settings(material_text, material_path=str(args.material))
            material_source = {"path": str(args.material), "size": len(raw_material),
                               "sha256": hashlib.sha256(raw_material).hexdigest()}
        except (OSError, UnicodeError, ValueError) as exc:
            parser.error(str(exc))
    rows = []
    for path in args.pac:
        try:
            if path.suffix.lower() != ".pac":
                raise ValueError("Expected a loose .pac file.")
            rows.append(inspect_pac(path.read_bytes(), path=str(path), material=material))
        except (OSError, ValueError) as exc:
            rows.append({"path": str(path), "status": "unavailable", "reason": str(exc)})
    report = {"format": "cdmw_pac_cloth_guide_study_v1", "assets": rows}
    if material_source is not None:
        report["material_profile"] = material_source
    print(json.dumps(report, indent=2, allow_nan=False))
    return int(any(row["status"] == "unavailable" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
