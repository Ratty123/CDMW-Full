from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_STAGES = ("VS", "PS")
BINDING_RE = re.compile(
    r"^;\s+"
    r"(?P<name>\S+)\s+"
    r"(?P<type>cbuffer|sampler|texture|uav|StructuredBuffer|ByteAddressBuffer|RWStructuredBuffer|RWByteAddressBuffer)\s+"
    r"(?P<format>\S+)\s+"
    r"(?P<dim>\S+)\s+"
    r"(?P<id>\S+)\s+"
    r"(?P<hlsl_bind>(?:cb|[stbu])\d+(?:,space\d+)?)"
    r"(?:(?P<count_inline>unbounded|-?\d+)|\s+(?P<count>unbounded|-?\d+))\s*$"
)
BIND_REGISTER_RE = re.compile(r"^(?P<prefix>cb|[stbu])(?P<register>\d+)(?:,space(?P<space>\d+))?$")
HANDLE_CREATE_RE = re.compile(
    r"createHandleFromBinding\(i32\s+217,\s+%dx\.types\.ResBind\s+\{\s+"
    r"i32\s+(?P<lower>-?\d+),\s+i32\s+(?P<upper>-?\d+),\s+i32\s+(?P<space>-?\d+),\s+i8\s+(?P<class>\d+)\s+\},\s+"
    r"i32\s+(?P<index>[^,]+),\s+i1\s+(?P<non_uniform>true|false)\)"
)
RESOURCE_CLASS_BY_ID = {
    0: "srv",
    1: "uav",
    2: "cbv",
    3: "sampler",
}


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _count(value: object) -> int | str:
    text = str(value or "").strip()
    if not text:
        return 0
    if text.lower() == "unbounded":
        return "unbounded"
    return _int(text)


def _u32le(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        return 0
    return int.from_bytes(data[offset : offset + 4], "little", signed=False)


def _dxbc_shader_model(data: bytes, offset: int) -> str:
    token = _u32le(data, offset)
    shader_type = token >> 16
    major = (token >> 4) & 0xF
    minor = token & 0xF
    stage_names = {
        0: "ps",
        1: "vs",
        2: "gs",
        3: "hs",
        4: "ds",
        5: "cs",
    }
    stage = stage_names.get(shader_type)
    return f"{stage}_{major}_{minor}" if stage else ""


def inspect_dxbc_container(data: bytes) -> dict[str, object]:
    sha256 = hashlib.sha256(data).hexdigest()
    if data[:4] != b"DXBC":
        return {
            "sha256": sha256,
            "size": len(data),
            "container_magic": data[:4].decode("ascii", "replace"),
            "container_kind": "unknown",
            "shader_ir": "unknown",
            "parts": [],
            "shader_model": "",
            "findings": ["not_dxbc_container"],
        }

    findings: list[str] = []
    container_size = _u32le(data, 24)
    part_count = _u32le(data, 28)
    parts: list[dict[str, object]] = []
    shader_model = ""
    if container_size and container_size != len(data):
        findings.append("dxbc_container_size_mismatch")
    if part_count > 256:
        findings.append("dxbc_part_count_suspicious")
        part_count = 0
    for index in range(part_count):
        offset = _u32le(data, 32 + index * 4)
        if offset + 8 > len(data):
            findings.append("dxbc_part_offset_out_of_range")
            continue
        tag = data[offset : offset + 4].decode("ascii", "replace")
        size = _u32le(data, offset + 4)
        part: dict[str, object] = {"tag": tag, "size": size, "offset": offset}
        if offset + 8 + size > len(data):
            part["truncated"] = True
            findings.append(f"{tag}_part_truncated")
        if tag in {"SHDR", "SHEX"}:
            model = _dxbc_shader_model(data, offset + 8)
            if model:
                part["shader_model"] = model
                shader_model = shader_model or model
        parts.append(part)
    tags = {str(part.get("tag", "")) for part in parts}
    shader_ir = "DXIL" if "DXIL" in tags else "DXBC_bytecode" if {"SHDR", "SHEX"} & tags else "unknown"
    return {
        "sha256": sha256,
        "size": len(data),
        "container_magic": "DXBC",
        "container_kind": "DXBC",
        "shader_ir": shader_ir,
        "parts": parts,
        "shader_model": shader_model,
        "findings": findings,
    }


def parse_resource_bindings_from_disassembly(text: str) -> list[dict[str, object]]:
    bindings: list[dict[str, object]] = []
    in_table = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip() == "; Resource Bindings:":
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith(";"):
            break
        if not line.strip() or "--------" in line or "Name" in line:
            continue
        match = BINDING_RE.match(line)
        if not match:
            if bindings:
                break
            continue
        payload = match.groupdict()
        register_match = BIND_REGISTER_RE.match(payload["hlsl_bind"])
        register = _int(register_match.group("register"), 0) if register_match else 0
        space = _int(register_match.group("space"), 0) if register_match and register_match.group("space") else 0
        count = _count(payload.get("count") or payload.get("count_inline"))
        payload.update(
            {
                "register": register,
                "space": space,
                "count": count,
                "bind_class": RESOURCE_CLASS_BY_ID.get({"t": 0, "u": 1, "cb": 2, "s": 3}.get(register_match.group("prefix") if register_match else "", -1), ""),
            }
        )
        payload.pop("count_inline", None)
        bindings.append(payload)
    return bindings


def parse_handle_creates_from_disassembly(text: str) -> list[dict[str, object]]:
    creates: list[dict[str, object]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        match = HANDLE_CREATE_RE.search(raw_line)
        if not match:
            continue
        class_id = _int(match.group("class"), -1)
        creates.append(
            {
                "line": line_number,
                "lower_bound": _int(match.group("lower")),
                "upper_bound": _int(match.group("upper")),
                "space": _int(match.group("space")),
                "class_id": class_id,
                "class": RESOURCE_CLASS_BY_ID.get(class_id, "unknown"),
                "index": match.group("index").strip(),
                "non_uniform": match.group("non_uniform") == "true",
                "is_unbounded": _int(match.group("upper"), 0) < 0,
            }
        )
    return creates


def zip_entry_name(blob_id: int) -> str:
    return f"{blob_id:06d}"


def candidate_shader_refs(candidate: Mapping[str, object], stages: Sequence[str] = DEFAULT_STAGES) -> list[dict[str, object]]:
    pipeline = _as_mapping(candidate.get("pipeline_description", {}))
    shaders = _as_mapping(pipeline.get("shaders", {}))
    refs: list[dict[str, object]] = []
    for stage in stages:
        shader = _as_mapping(shaders.get(stage, {}))
        blob_id = _int(shader.get("blob_id", 0))
        if not blob_id:
            continue
        refs.append(
            {
                "stage": stage,
                "blob_id": blob_id,
                "byte_length": _int(shader.get("byte_length", shader.get("bytecode_length", 0))),
            }
        )
    return refs


def _selected_candidates(
    report: Mapping[str, object],
    *,
    ranks: Sequence[int],
    chunk_indices: Sequence[int],
    limit: int,
) -> list[Mapping[str, object]]:
    candidates = [item for item in _as_sequence(report.get("candidates", ())) if isinstance(item, Mapping)]
    rank_set = {int(rank) for rank in ranks if int(rank or 0)}
    chunk_set = {int(chunk) for chunk in chunk_indices if int(chunk or 0)}
    selected: list[Mapping[str, object]] = []
    for candidate in candidates:
        rank = _int(candidate.get("rank", 0))
        chunk = _int(candidate.get("chunk_index", 0))
        if rank_set and rank not in rank_set:
            continue
        if chunk_set and chunk not in chunk_set:
            continue
        selected.append(candidate)
        if limit and len(selected) >= limit:
            break
    return selected


def find_shader_disassembler(explicit: str = "") -> dict[str, object]:
    if explicit:
        path = Path(explicit)
        tool = "dxcompiler_dll" if path.suffix.lower() == ".dll" else "dxc"
        return {"status": "available" if path.is_file() else "not_found", "tool": tool, "path": str(path)}
    dxc = shutil.which("dxc")
    if dxc:
        return {"status": "available", "tool": "dxc", "path": dxc}
    fxc = shutil.which("fxc")
    if fxc:
        return {"status": "available", "tool": "fxc", "path": fxc}
    repo_root = Path(__file__).resolve().parents[1]
    dxcompiler = repo_root / ".tools" / "renderdoc" / "1.44" / "RenderDoc_1.44_64" / "plugins" / "d3d12" / "dxcompiler.dll"
    if dxcompiler.is_file():
        return {
            "status": "available" if os.name == "nt" else "blocked",
            "tool": "dxcompiler_dll",
            "path": str(dxcompiler),
            "reason": "" if os.name == "nt" else "dxcompiler.dll backend requires Windows.",
        }
    return {"status": "not_detected", "tool": "", "path": ""}


def _guid_bytes(text: str) -> ctypes.Array[ctypes.c_ubyte]:
    import uuid

    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


def _com_method(ptr: ctypes.c_void_p, index: int, restype: object, *argtypes: object) -> object:
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _com_release(ptr: ctypes.c_void_p) -> None:
    if ptr and ptr.value:
        _com_method(ptr, 2, ctypes.c_ulong)(ptr)


def _hresult_hex(value: object) -> str:
    try:
        return hex(ctypes.c_ulong(int(value)).value)
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _run_dxcompiler_dll_disassembler(dxcompiler_path: Path, shader_path: Path, asm_path: Path) -> dict[str, object]:
    if os.name != "nt":
        return {"status": "failed", "path": "", "error": "dxcompiler.dll backend requires Windows"}

    HRESULT = ctypes.c_long
    c_void_pp = ctypes.POINTER(ctypes.c_void_p)
    dll_dir = None
    library = ctypes.c_void_p()
    compiler = ctypes.c_void_p()
    source_blob = ctypes.c_void_p()
    disassembly_blob = ctypes.c_void_p()
    try:
        if hasattr(os, "add_dll_directory"):
            dll_dir = os.add_dll_directory(str(dxcompiler_path.parent))
        dll = ctypes.WinDLL(str(dxcompiler_path))
        create_instance = dll.DxcCreateInstance
        create_instance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, c_void_pp]
        create_instance.restype = HRESULT

        clsid_library = _guid_bytes("6245D6AF-66E0-48FD-80B4-4D271796748C")
        iid_library = _guid_bytes("e5204dc7-d18c-4c3c-bdfb-851673980fe7")
        clsid_compiler = _guid_bytes("73E22D93-E6CE-47F3-B5BF-F0664F39C1B0")
        iid_compiler = _guid_bytes("8c210bf3-011f-4422-8d70-6f9acb8db617")

        hr = create_instance(ctypes.byref(clsid_library), ctypes.byref(iid_library), ctypes.byref(library))
        if hr != 0:
            return {"status": "failed", "path": "", "error": f"DxcLibrary create failed {_hresult_hex(hr)}"}
        hr = create_instance(ctypes.byref(clsid_compiler), ctypes.byref(iid_compiler), ctypes.byref(compiler))
        if hr != 0:
            return {"status": "failed", "path": "", "error": f"DxcCompiler create failed {_hresult_hex(hr)}"}

        create_blob_from_file = _com_method(library, 5, HRESULT, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32), c_void_pp)
        hr = create_blob_from_file(library, str(shader_path), None, ctypes.byref(source_blob))
        if hr != 0:
            return {"status": "failed", "path": "", "error": f"CreateBlobFromFile failed {_hresult_hex(hr)}"}

        disassemble = _com_method(compiler, 5, HRESULT, ctypes.c_void_p, c_void_pp)
        hr = disassemble(compiler, source_blob, ctypes.byref(disassembly_blob))
        if hr != 0:
            return {"status": "failed", "path": "", "error": f"Disassemble failed {_hresult_hex(hr)}"}

        get_buffer_pointer = _com_method(disassembly_blob, 3, ctypes.c_void_p)
        get_buffer_size = _com_method(disassembly_blob, 4, ctypes.c_size_t)
        pointer = get_buffer_pointer(disassembly_blob)
        size = get_buffer_size(disassembly_blob)
        text = ctypes.string_at(pointer, size).rstrip(b"\0").decode("utf-8", "replace")
        asm_path.write_text(text, encoding="utf-8")
        return {"status": "ok", "path": str(asm_path), "error": ""}
    except (AttributeError, OSError, ValueError) as exc:
        return {"status": "failed", "path": "", "error": str(exc)}
    finally:
        _com_release(disassembly_blob)
        _com_release(source_blob)
        _com_release(compiler)
        _com_release(library)
        if dll_dir is not None:
            dll_dir.close()


def _run_disassembler(disassembler: Mapping[str, object], shader_path: Path, asm_path: Path) -> dict[str, object]:
    if disassembler.get("status") != "available":
        return {"status": "not_available", "path": "", "error": str(disassembler.get("reason", ""))}
    tool_path = str(disassembler.get("path", ""))
    tool = str(disassembler.get("tool", ""))
    if tool == "dxcompiler_dll":
        return _run_dxcompiler_dll_disassembler(Path(tool_path), shader_path, asm_path)
    asm_path.parent.mkdir(parents=True, exist_ok=True)
    if tool == "dxc":
        command = [tool_path, "-dumpbin", "-Fc", str(asm_path), str(shader_path)]
    else:
        command = [tool_path, "/dumpbin", str(shader_path)]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    except OSError as exc:
        return {"status": "failed", "path": "", "error": str(exc)}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "path": "", "error": "timeout"}
    if completed.returncode != 0:
        return {
            "status": "failed",
            "path": "",
            "error": (completed.stderr or completed.stdout or "").strip()[:2000],
        }
    if tool != "dxc":
        asm_path.write_text(completed.stdout, encoding="utf-8", errors="replace")
    return {"status": "ok", "path": str(asm_path), "error": ""}


def extract_shader_blobs(
    draw_candidate_report: Mapping[str, object],
    *,
    renderdoc_zip: Path,
    out_dir: Path,
    ranks: Sequence[int] = (),
    chunk_indices: Sequence[int] = (),
    stages: Sequence[str] = DEFAULT_STAGES,
    limit: int = 0,
    disassemble: bool = False,
    disassembler_path: str = "",
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = _selected_candidates(draw_candidate_report, ranks=ranks, chunk_indices=chunk_indices, limit=limit)
    disassembler = find_shader_disassembler(disassembler_path) if disassemble else {"status": "not_requested", "tool": "", "path": ""}
    blobs: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    with zipfile.ZipFile(renderdoc_zip) as archive:
        names = set(archive.namelist())
        for candidate in selected:
            rank = _int(candidate.get("rank", 0))
            chunk_index = _int(candidate.get("chunk_index", 0))
            for shader in candidate_shader_refs(candidate, stages):
                blob_id = _int(shader.get("blob_id", 0))
                entry = zip_entry_name(blob_id)
                if entry not in names:
                    missing.append({"rank": rank, "chunk_index": chunk_index, "stage": shader.get("stage", ""), "blob_id": blob_id, "entry": entry})
                    continue
                data = archive.read(entry)
                stage = str(shader.get("stage", ""))
                suffix = ".dxil" if b"DXIL" in data[: min(len(data), 65536)] else ".dxbc"
                out_path = out_dir / f"rank{rank}_chunk{chunk_index}_{stage}_blob{entry}{suffix}"
                out_path.write_bytes(data)
                inspection = inspect_dxbc_container(data)
                expected_length = _int(shader.get("byte_length", 0))
                findings = list(_as_sequence(inspection.get("findings", ())))
                if expected_length and expected_length != len(data):
                    findings.append("byte_length_mismatch")
                asm_status = {"status": "not_requested", "path": "", "error": ""}
                resource_bindings: list[dict[str, object]] = []
                handle_creates: list[dict[str, object]] = []
                if disassemble:
                    asm_status = _run_disassembler(disassembler, out_path, out_path.with_suffix(".asm"))
                    asm_path = Path(str(asm_status.get("path", "")))
                    if asm_path.is_file():
                        asm_text = asm_path.read_text(encoding="utf-8", errors="replace")
                        resource_bindings = parse_resource_bindings_from_disassembly(asm_text)
                        handle_creates = parse_handle_creates_from_disassembly(asm_text)
                blobs.append(
                    {
                        "rank": rank,
                        "chunk_index": chunk_index,
                        "stage": stage,
                        "blob_id": blob_id,
                        "entry": entry,
                        "expected_byte_length": expected_length,
                        "path": str(out_path),
                        "disassembly_status": asm_status.get("status", ""),
                        "disassembly_path": asm_status.get("path", ""),
                        "disassembly_error": asm_status.get("error", ""),
                        "resource_bindings": resource_bindings,
                        "handle_creates": handle_creates,
                        **{key: value for key, value in inspection.items() if key != "findings"},
                        "findings": findings,
                    }
                )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "renderdoc_zip_shader_blobs",
        "renderdoc_zip": str(renderdoc_zip),
        "candidate_count": len(selected),
        "blob_count": len(blobs),
        "missing_count": len(missing),
        "disassembler": disassembler,
        "blobs": blobs,
        "missing": missing,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract shader bytecode blobs referenced by RenderDoc draw candidates.")
    parser.add_argument("--draw-candidates-json", required=True)
    parser.add_argument("--renderdoc-zip", required=True, help="RenderDoc zip sidecar from zip.xml conversion.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--rank", action="append", type=int, default=[])
    parser.add_argument("--chunk-index", action="append", type=int, default=[])
    parser.add_argument("--stage", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--disassemble", action="store_true")
    parser.add_argument("--dxc", default="", help="Optional explicit dxc.exe path for DXIL dump.")
    parser.add_argument("--dxcompiler-dll", default="", help="Optional explicit dxcompiler.dll path for DXIL dump.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = json.loads(Path(args.draw_candidates_json).read_text(encoding="utf-8"))
    if not isinstance(report, Mapping):
        raise ValueError("draw candidate report must be an object")
    output = extract_shader_blobs(
        report,
        renderdoc_zip=Path(args.renderdoc_zip),
        out_dir=Path(args.out_dir),
        ranks=args.rank,
        chunk_indices=args.chunk_index,
        stages=tuple(args.stage or DEFAULT_STAGES),
        limit=int(args.limit or 0),
        disassemble=bool(args.disassemble),
        disassembler_path=str(args.dxc or args.dxcompiler_dll or ""),
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {output['blob_count']} shader blob(s): {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
