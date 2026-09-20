"""Inspect loose, decoded PAC guide meshes without modifying the input files.

Run with one or more .pac paths. JSON on stdout includes source hashes, guide
bounds, topology, packed skin bindings, raw channels and byte-range provenance.
It does not assign pin, mass or stiffness meanings to undecoded fields.
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

from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides


def inspect_pac(data: bytes, *, path: str = "") -> dict:
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
    return {**result, "status": "decoded", "vertex_count": len(guides.vertices),
            "triangle_count": len(guides.triangles), "guides": payload,
            "limitations": "Raw byte channels, alpha bits and constraint tables are not physical-pin or solver settings. No runtime parity is implied."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pac", type=Path, nargs="+", help="Loose decompressed .pac files, read-only.")
    args = parser.parse_args(argv)
    rows = []
    for path in args.pac:
        try:
            if path.suffix.lower() != ".pac":
                raise ValueError("Expected a loose .pac file.")
            rows.append(inspect_pac(path.read_bytes(), path=str(path)))
        except (OSError, ValueError) as exc:
            rows.append({"path": str(path), "status": "unavailable", "reason": str(exc)})
    print(json.dumps({"format": "cdmw_pac_cloth_guide_study_v1", "assets": rows}, indent=2, allow_nan=False))
    return int(any(row["status"] == "unavailable" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
