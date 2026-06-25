from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence
import zipfile


def zip_entry_name(blob_id: object) -> str:
    return f"{int(blob_id):06d}"


def inspect_dxbc_container(data: bytes) -> dict[str, Any]:
    if not data.startswith(b"DXBC") or len(data) < 32:
        return {"container_kind": "unknown", "shader_ir": "", "parts": []}
    part_count = int.from_bytes(data[28:32], "little", signed=False)
    parts: list[dict[str, Any]] = []
    for index in range(part_count):
        offset = int.from_bytes(data[32 + index * 4 : 36 + index * 4], "little", signed=False)
        if offset + 8 > len(data):
            continue
        tag = data[offset : offset + 4].decode("ascii", errors="replace")
        size = int.from_bytes(data[offset + 4 : offset + 8], "little", signed=False)
        parts.append({"tag": tag, "offset": offset, "size": size})
    shader_ir = "DXIL" if any(part["tag"] == "DXIL" for part in parts) else ("DXBC" if parts else "")
    return {"container_kind": "DXBC", "shader_ir": shader_ir, "parts": parts}


def candidate_shader_refs(candidate: Mapping[str, Any], *, stages: Sequence[str] = ("VS", "PS", "CS")) -> list[dict[str, Any]]:
    shaders = candidate.get("pipeline_description", {}).get("shaders", {}) if isinstance(candidate.get("pipeline_description"), Mapping) else {}
    refs: list[dict[str, Any]] = []
    for stage in stages:
        shader = shaders.get(stage, {}) if isinstance(shaders, Mapping) else {}
        if isinstance(shader, Mapping) and int(shader.get("blob_id", 0) or 0):
            refs.append({"stage": stage, "blob_id": int(shader.get("blob_id", 0)), "byte_length": int(shader.get("byte_length", 0) or 0)})
    return refs


_BIND_RE = re.compile(r"^(?P<name>\S+)\s+(?P<type>\S+)\s+(?P<format>\S+)\s+(?P<dim>\S+)\s+(?P<id>\S+)\s+(?P<hlsl>\S+)(?:\s+(?P<count>\S+))?")
_HLSL_RE = re.compile(r"(?P<prefix>cb|[tus])(?P<register>\d+),space(?P<space>\d+)(?P<unbounded>unbounded)?", re.IGNORECASE)


def parse_resource_bindings_from_disassembly(text: str) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    active = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(";"):
            line = line[1:].strip()
        if not active:
            active = line == "Resource Bindings:"
            continue
        if not line or line.startswith("-") or line.startswith("Name "):
            continue
        if "target datalayout" in line:
            break
        match = _BIND_RE.match(line)
        if not match:
            continue
        hlsl = match.group("hlsl")
        bind = _HLSL_RE.search(hlsl)
        count: Any = match.group("count") or 1
        if bind and bind.group("unbounded"):
            count = "unbounded"
        elif isinstance(count, str) and count.isdigit():
            count = int(count)
        bindings.append(
            {
                "name": match.group("name"),
                "type": match.group("type"),
                "format": match.group("format"),
                "dim": match.group("dim"),
                "id": match.group("id"),
                "hlsl_bind": hlsl,
                "register": int(bind.group("register")) if bind else "",
                "space": int(bind.group("space")) if bind else "",
                "count": count,
            }
        )
    return bindings


_HANDLE_RE = re.compile(
    r"createHandleFromBinding.*?ResBind \{ i32 (?P<class>-?\d+), i32 (?P<count>-?\d+), i32 (?P<space>-?\d+), i8 (?P<flags>-?\d+) \}, i32 (?P<index>%?\w+), i1 (?P<nonuniform>true|false)"
)


def parse_handle_creates_from_disassembly(text: str) -> list[dict[str, Any]]:
    classes = {0: "srv", 1: "uav", 2: "cbv", 3: "sampler"}
    creates: list[dict[str, Any]] = []
    for match in _HANDLE_RE.finditer(text):
        cls = int(match.group("class"))
        count = int(match.group("count"))
        creates.append(
            {
                "class": classes.get(cls, str(cls)),
                "space": int(match.group("space")),
                "index": match.group("index"),
                "is_unbounded": count < 0,
                "non_uniform": match.group("nonuniform") == "true",
            }
        )
    return creates


def _wanted_ranks(ranks: Iterable[int] | None) -> set[int] | None:
    return {int(rank) for rank in ranks} if ranks else None


def extract_shader_blobs(
    candidate_report: Mapping[str, Any],
    *,
    renderdoc_zip: Path,
    out_dir: Path,
    ranks: Iterable[int] | None = None,
    stages: Sequence[str] = ("VS", "PS", "CS"),
    dxc: Path | None = None,
) -> dict[str, Any]:
    wanted = _wanted_ranks(ranks)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    blobs: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    with zipfile.ZipFile(renderdoc_zip) as archive:
        names = set(archive.namelist())
        for candidate in candidate_report.get("candidates", []):
            if not isinstance(candidate, Mapping):
                continue
            rank = int(candidate.get("rank", 0) or 0)
            if wanted is not None and rank not in wanted:
                continue
            for ref in candidate_shader_refs(candidate, stages=stages):
                entry = zip_entry_name(ref["blob_id"])
                if entry not in names:
                    missing.append({**ref, "rank": rank, "chunk_index": candidate.get("chunk_index", ""), "entry": entry})
                    continue
                data = archive.read(entry)
                target = out / f"rank{rank:02d}_{ref['stage']}_{entry}.bin"
                target.write_bytes(data)
                inspection = inspect_dxbc_container(data)
                disassembly_path = ""
                disassembly_status = "not_requested"
                resource_bindings: list[dict[str, Any]] = []
                handle_creates: list[dict[str, Any]] = []
                if dxc and data:
                    disassembly_path = str(target.with_suffix(".asm"))
                    try:
                        completed = subprocess.run([str(dxc), "-dumpbin", str(target)], check=False, capture_output=True, text=True, timeout=120)
                    except (OSError, subprocess.SubprocessError) as exc:
                        disassembly_status = f"failed: {exc}"
                    else:
                        if completed.returncode == 0:
                            Path(disassembly_path).write_text(completed.stdout, encoding="utf-8")
                            disassembly_status = "ok"
                            resource_bindings = parse_resource_bindings_from_disassembly(completed.stdout)
                            handle_creates = parse_handle_creates_from_disassembly(completed.stdout)
                        else:
                            disassembly_status = f"failed: {completed.stderr.strip() or completed.returncode}"
                blobs.append(
                    {
                        **ref,
                        "rank": rank,
                        "chunk_index": candidate.get("chunk_index", ""),
                        "entry": entry,
                        "path": str(target),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        **inspection,
                        "resource_bindings": resource_bindings,
                        "handle_creates": handle_creates,
                        "disassembly_status": disassembly_status,
                        "disassembly_path": disassembly_path,
                    }
                )
    return {
        "status": "shader_blobs_extracted",
        "renderdoc_zip": str(renderdoc_zip),
        "blob_count": len(blobs),
        "missing_count": len(missing),
        "blobs": blobs,
        "missing": missing,
        "disassembler": {"status": "used" if dxc else "not_requested", "path": str(dxc or "")},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draw-candidates-json", type=Path, required=True)
    parser.add_argument("--renderdoc-zip", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--rank", type=int, action="append")
    parser.add_argument("--dxc", type=Path)
    args = parser.parse_args(argv)
    report = json.loads(args.draw_candidates_json.read_text(encoding="utf-8"))
    output = extract_shader_blobs(report, renderdoc_zip=args.renderdoc_zip, out_dir=args.out_dir, ranks=args.rank, dxc=args.dxc)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
