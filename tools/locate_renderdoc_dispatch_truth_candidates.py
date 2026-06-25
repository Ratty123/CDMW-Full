from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from tools.renderdoc_xml_common import (
    as_int,
    chunk_index,
    chunks,
    load_xml,
    named_value,
    parse_pipeline_states,
    parse_root_signatures,
)


def locate_dispatch_truth_candidates(xml_path: Path) -> dict[str, Any]:
    root = load_xml(Path(xml_path))
    psos = parse_pipeline_states(root)
    roots = parse_root_signatures(root)
    state_by_command: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    for chunk in chunks(root):
        name = chunk.attrib.get("name", "")
        command_list = str(named_value(chunk, "pCommandList", ""))
        if command_list and command_list not in state_by_command:
            state_by_command[command_list] = {}
        state = state_by_command.get(command_list, {})
        if "SetPipelineState" in name and command_list:
            state["pipeline_state"] = as_int(named_value(chunk, "pPipelineState", 0))
        elif "SetComputeRootSignature" in name and command_list:
            state["compute_root_signature"] = as_int(named_value(chunk, "pRootSignature", 0))
        elif name.endswith("::Dispatch") or "CommandList::Dispatch" in name:
            groups = {
                "x": as_int(named_value(chunk, "ThreadGroupCountX", 0)),
                "y": as_int(named_value(chunk, "ThreadGroupCountY", 0)),
                "z": as_int(named_value(chunk, "ThreadGroupCountZ", 0)),
            }
            groups["total"] = groups["x"] * groups["y"] * groups["z"]
            pso = state.get("pipeline_state", 0)
            root_sig = state.get("compute_root_signature", 0) or psos.get(str(pso), {}).get("root_signature", 0)
            candidates.append(
                {
                    "rank": len(candidates) + 1,
                    "chunk_index": chunk_index(chunk),
                    "command_list": as_int(command_list),
                    "dispatch_groups": groups,
                    "state": {"pipeline_state": pso, "compute_root_signature": root_sig},
                    "pipeline_description": psos.get(str(pso), {}),
                    "root_signature_description": roots.get(str(root_sig), {}),
                }
            )
    return {
        "status": "dispatch_candidates_located",
        "capture_xml": str(xml_path),
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args(argv)
    report = locate_dispatch_truth_candidates(args.xml)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
