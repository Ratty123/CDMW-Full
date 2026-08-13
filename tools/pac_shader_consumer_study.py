"""Phase 2 of the PAC vertex channel study: map disk bytes to the real consumer.

Read-only. The game ships its shader cache as ``.padxil`` entries inside the
archives, each a ``PASC`` container wrapping a DXIL shader. Those shaders are the
consumer the plan at ``docs/plans/active/pac-vertex-channel-identification-v1.md``
says must be identified before any lane can move from protected to owned, and
they turn out to answer the question directly rather than by inference:

* the character vertex shaders take **no** vertex-input semantics at all, only
  ``SV_VertexID``, and pull vertex data themselves out of a ``StructuredBuffer``
  whose declared stride is 40, the PAC record stride exactly;
* the shader's own reflection metadata names that struct's fields, so the record
  layout is read off the consumer rather than guessed from statistics;
* the DXIL then says, per field, which bits it actually consumes.

The last point is what makes this worth doing properly. A field being declared
is not the same as its bits being read, so this tool runs a small conservative
def-use pass over the disassembly: a bit counts as used unless the instructions
prove it is masked away. The bias is deliberate. Claiming a byte is unread is the
"padding" hypothesis, which the plan calls the hardest one to establish, so every
ambiguity resolves towards "used".

Disassembly is done by ``dxc.exe`` from the installed Windows SDK. That is a
Microsoft tool already on the machine, not a new dependency vendored into this
repository, and it is invoked read-only on a copy under system TEMP.

What this tool cannot tell you: what the CPU side does before upload. It proves
what the GPU is handed and what the GPU does with it. The plan is explicit that
if the engine repacks vertices then a shader offset alone does not identify a PAC
offset, so the report carries the evidence for the 1:1 mapping rather than
asserting it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt
from cdmw.models import ArchiveEntry

REPORT_FORMAT = "cdmw_pac_shader_consumer_v1"
STUDY_PHASE = "phase-2"
PLAN_PATH = "docs/plans/active/pac-vertex-channel-identification-v1.md"

#: The PAC record stride this study is about.
PROVEN_PAC_STRIDE = 40
#: Cheap prefilter: the field name appears as a raw string in the container.
RECORD_MARKER = b"_normalizedPackedPosition"

_DEFAULT_DXC_GLOBS = (
    r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\dxc.exe",
    r"C:\Program Files\Windows Kits\10\bin\*\x64\dxc.exe",
)


def locate_dxc(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    for pattern in _DEFAULT_DXC_GLOBS:
        root = Path(pattern).parts[0]
        try:
            matches = sorted(Path(root).glob(str(Path(*Path(pattern).parts[1:]))))
        except OSError:
            continue
        if matches:
            return matches[-1]
    return None


# ── PASC container ───────────────────────────────────────────────────

@dataclass(frozen=True)
class PascContainer:
    """A shipped shader: the PASC wrapper's source name plus the DXIL inside."""

    source_hlsl: str
    container: bytes

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.container).hexdigest()


def parse_pasc(data: bytes) -> PascContainer | None:
    if len(data) < 40 or data[:4] != b"PASC":
        return None
    name_length = struct.unpack_from("<I", data, 32)[0]
    if name_length > 512 or 36 + name_length > len(data):
        return None
    source = data[36:36 + name_length].decode("utf-8", "replace")
    start = data.find(b"DXBC")
    if start < 0:
        return None
    return PascContainer(source_hlsl=source, container=data[start:])


# ── Disassembly parsing ──────────────────────────────────────────────

_STRUCT_FIELD_RE = re.compile(r";\s+(?P<type>[A-Za-z_][\w<>, ]*?)\s+(?P<name>\w+)(?:\[\d+\])?;\s+; Offset:\s+(?P<offset>\d+)")
_BIND_INFO_RE = re.compile(r"; Resource bind info for (?P<name>\S+)")
_STRUCT_SIZE_RE = re.compile(r"\}\s+\$Element;\s+; Offset:\s+0 Size:\s+(?P<size>\d+)")
_ANNOTATE_RE = re.compile(
    r"^\s*(?P<result>%\d+) = call %dx\.types\.Handle @dx\.op\.annotateHandle\(.*?resource: (?P<kind>\w+)<stride=(?P<stride>\d+)>"
)
_RAW_LOAD_RE = re.compile(
    r"^\s*(?P<result>%\d+) = call %dx\.types\.ResRet\.(?P<ret>\w+) @dx\.op\.rawBufferLoad\.\w+\("
    r"i32 \d+, %dx\.types\.Handle (?P<handle>%\d+), i32 (?P<index>[%\w]+), i32 (?P<offset>\d+), "
    r"i8 (?P<mask>\d+), i32 (?P<align>\d+)\)"
)
_EXTRACT_RE = re.compile(r"^\s*(?P<result>%\d+) = extractvalue %dx\.types\.ResRet\.\w+ (?P<source>%\d+), (?P<slot>\d+)")
_ASSIGN_RE = re.compile(r"^\s*(?P<result>%\d+) = (?P<body>.+)$")
_SIG_ROW_RE = re.compile(
    r"^;\s+(?P<name>[A-Za-z_]\w*)\s+(?P<index>\d+)\s+(?P<mask>[xyzw ]+)\s+(?P<reg>\d+)\s+(?P<sysvalue>\w+)\s+(?P<format>\w+)"
)
_PSV_SIG_RE = re.compile(r"^;\s+(?P<name>[A-Za-z_]\w*)\s+(?P<index>\d+)\s+(?P<interp>[a-zA-Z]+)\s*$")


@dataclass
class StructField:
    name: str
    type_name: str
    offset: int

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "type": self.type_name, "offset": self.offset}


@dataclass
class RecordLoad:
    """One ``rawBufferLoad`` against the 40-byte vertex record."""

    element_offset: int
    mask: int
    return_type: str
    components: dict[int, str] = field(default_factory=dict)

    @property
    def component_size(self) -> int:
        return 2 if self.return_type == "f16" else 4

    def byte_span(self) -> tuple[int, int]:
        size = self.component_size
        lanes = [slot for slot in range(4) if (self.mask >> slot) & 1]
        first, last = min(lanes), max(lanes)
        return self.element_offset + first * size, self.element_offset + (last + 1) * size


def _parse_struct_fields(lines: Sequence[str]) -> tuple[list[StructField], int]:
    """Fields of the vertex record, straight out of the shader's reflection."""
    fields: list[StructField] = []
    size = 0
    inside = False
    for line in lines:
        if _BIND_INFO_RE.search(line):
            inside = True
            fields = []
            size = 0
            continue
        if not inside:
            continue
        size_match = _STRUCT_SIZE_RE.search(line)
        if size_match:
            size = int(size_match.group("size"))
            if size == PROVEN_PAC_STRIDE and fields:
                return fields, size
            inside = False
            continue
        field_match = _STRUCT_FIELD_RE.search(line)
        if field_match:
            fields.append(
                StructField(
                    name=field_match.group("name"),
                    type_name=field_match.group("type").strip(),
                    offset=int(field_match.group("offset")),
                )
            )
    return ([], 0)


def _parse_signatures(lines: Sequence[str]) -> dict[str, list[dict[str, object]]]:
    signatures: dict[str, list[dict[str, object]]] = {"input": [], "output": []}
    section: str | None = None
    seen_psv = False
    for line in lines:
        if "PSVRuntimeInfo" in line:
            seen_psv = True
        if line.startswith("; Input signature:"):
            section = "input"
            continue
        if line.startswith("; Output signature:"):
            section = "output"
            continue
        if section is None:
            continue
        if not line.startswith(";"):
            section = None
            continue
        if seen_psv:
            match = _PSV_SIG_RE.match(line)
            if match and match.group("name") not in {"Name"}:
                for row in signatures[section]:
                    if row["name"] == match.group("name") and row["index"] == int(match.group("index")):
                        row["interpolation"] = match.group("interp")
            continue
        match = _SIG_ROW_RE.match(line)
        if match and match.group("name") != "Name":
            signatures[section].append(
                {
                    "name": match.group("name"),
                    "index": int(match.group("index")),
                    "mask": match.group("mask").strip(),
                    "register": int(match.group("reg")),
                    "sysvalue": match.group("sysvalue"),
                    "format": match.group("format"),
                    "interpolation": "",
                }
            )
    return signatures


def _shader_stage(lines: Sequence[str]) -> str:
    for line in lines:
        stripped = line.strip("; \t")
        if stripped.endswith("Shader") and stripped.split(" ")[0] in {
            "Vertex", "Pixel", "Geometry", "Hull", "Domain", "Compute", "Amplification", "Mesh",
        }:
            return stripped
    return "unknown"


# ── Conservative bit usage ───────────────────────────────────────────

_FULL = 0xFFFFFFFF


class BitUsage:
    """Which bits of an SSA value reach anything, resolved conservatively.

    Only three instructions narrow a value: ``and`` with a literal, ``lshr`` with
    a literal, and ``trunc``. Everything else is treated as consuming the whole
    operand. That direction matters: this analysis is the evidence behind any
    claim that a byte is unread, so it must never under-report use.
    """

    def __init__(self, lines: Sequence[str]) -> None:
        self._defs: dict[str, str] = {}
        self._uses: dict[str, list[str]] = defaultdict(list)
        for line in lines:
            match = _ASSIGN_RE.match(line)
            if match:
                self._defs[match.group("result")] = match.group("body")
            for token in set(re.findall(r"%\d+", line)):
                if match and token == match.group("result"):
                    continue
                self._uses[token].append(line)

    def used_bits(self, value: str, *, depth: int = 0, seen: frozenset[str] = frozenset()) -> int:
        if depth > 24 or value in seen:
            return _FULL
        seen = seen | {value}
        uses = self._uses.get(value, [])
        if not uses:
            return 0
        total = 0
        for line in uses:
            total |= self._bits_from_use(value, line, depth=depth, seen=seen)
            if total == _FULL:
                return _FULL
        return total

    def _bits_from_use(self, value: str, line: str, *, depth: int, seen: frozenset[str]) -> int:
        match = _ASSIGN_RE.match(line)
        if match is None:
            # A store, a call argument, an output write: the whole value escapes.
            return _FULL
        result = match.group("result")
        body = match.group("body")

        and_match = re.match(rf"and i32 {re.escape(value)}, (-?\d+)$", body) or re.match(
            rf"and i32 (-?\d+), {re.escape(value)}$", body
        )
        if and_match:
            literal = int(and_match.group(1)) & _FULL
            downstream = self.used_bits(result, depth=depth + 1, seen=seen)
            return literal & downstream

        shr_match = re.match(rf"lshr i32 {re.escape(value)}, (\d+)$", body)
        if shr_match:
            shift = int(shr_match.group(1))
            downstream = self.used_bits(result, depth=depth + 1, seen=seen)
            return (downstream << shift) & _FULL

        trunc_match = re.match(rf"trunc i32 {re.escape(value)} to i(\d+)$", body)
        if trunc_match:
            width = int(trunc_match.group(1))
            downstream = self.used_bits(result, depth=depth + 1, seen=seen)
            return downstream & ((1 << width) - 1)

        if re.match(rf"(zext|bitcast) i\d+ {re.escape(value)} to ", body):
            return self.used_bits(result, depth=depth + 1, seen=seen)

        return _FULL


# ── One shader ───────────────────────────────────────────────────────

@dataclass
class ShaderStudy:
    digest: str
    source_hlsl: str
    stage: str
    struct_fields: list[StructField]
    struct_size: int
    loads: list[RecordLoad]
    byte_read: list[bool]
    byte_used: list[bool]
    signatures: dict[str, list[dict[str, object]]]
    archive_paths: list[str] = field(default_factory=list)
    occurrences: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "source_hlsl": self.source_hlsl,
            "stage": self.stage,
            "occurrences": self.occurrences,
            "archive_paths": self.archive_paths[:4],
            "record_struct": {
                "size": self.struct_size,
                "fields": [value.to_dict() for value in self.struct_fields],
            },
            "loads": [
                {
                    "element_offset": load.element_offset,
                    "mask": load.mask,
                    "return_type": load.return_type,
                    "byte_span": list(load.byte_span()),
                }
                for load in self.loads
            ],
            "bytes_read": [index for index, value in enumerate(self.byte_read) if value],
            "bytes_used": [index for index, value in enumerate(self.byte_used) if value],
            "bytes_read_not_used": [
                index for index in range(PROVEN_PAC_STRIDE) if self.byte_read[index] and not self.byte_used[index]
            ],
            "signatures": self.signatures,
            "notes": self.notes,
        }


def analyse_disassembly(text: str, *, digest: str, source_hlsl: str) -> ShaderStudy | None:
    lines = text.splitlines()
    fields, size = _parse_struct_fields(lines)
    if size != PROVEN_PAC_STRIDE:
        return None

    # Handles annotated as a stride-40 structured buffer are the vertex record.
    record_handles: set[str] = set()
    for line in lines:
        match = _ANNOTATE_RE.match(line)
        if match and int(match.group("stride")) == PROVEN_PAC_STRIDE:
            record_handles.add(match.group("result"))
    if not record_handles:
        return None

    loads: dict[str, RecordLoad] = {}
    for line in lines:
        match = _RAW_LOAD_RE.match(line)
        if match and match.group("handle") in record_handles:
            loads[match.group("result")] = RecordLoad(
                element_offset=int(match.group("offset")),
                mask=int(match.group("mask")),
                return_type=match.group("ret"),
            )
    if not loads:
        return None

    for line in lines:
        match = _EXTRACT_RE.match(line)
        if match and match.group("source") in loads:
            loads[match.group("source")].components[int(match.group("slot"))] = match.group("result")

    usage = BitUsage(lines)
    byte_read = [False] * PROVEN_PAC_STRIDE
    byte_used = [False] * PROVEN_PAC_STRIDE
    notes: list[str] = []

    for load in loads.values():
        size_of = load.component_size
        for slot in range(4):
            if not (load.mask >> slot) & 1:
                continue
            base = load.element_offset + slot * size_of
            if base + size_of > PROVEN_PAC_STRIDE:
                notes.append(f"load at {load.element_offset} slot {slot} runs past the record")
                continue
            for offset in range(base, base + size_of):
                byte_read[offset] = True
            ssa = load.components.get(slot)
            if ssa is None:
                # Loaded but never extracted: read by the hardware, used by nothing.
                continue
            if size_of == 2:
                # A half component is atomic here; any use marks both its bytes.
                if usage.used_bits(ssa) != 0:
                    byte_used[base] = True
                    byte_used[base + 1] = True
                continue
            bits = usage.used_bits(ssa)
            for byte_index in range(4):
                if (bits >> (byte_index * 8)) & 0xFF:
                    byte_used[base + byte_index] = True

    return ShaderStudy(
        digest=digest,
        source_hlsl=source_hlsl,
        stage=_shader_stage(lines),
        struct_fields=fields,
        struct_size=size,
        loads=sorted(loads.values(), key=lambda value: value.element_offset),
        byte_read=byte_read,
        byte_used=byte_used,
        signatures=_parse_signatures(lines),
        notes=notes,
    )


# ── Corpus walk ──────────────────────────────────────────────────────

def iter_shader_entries(game_root: Path) -> Iterable[ArchiveEntry]:
    for pamt in discover_pamt_files(game_root):
        for entry in parse_archive_pamt(pamt):
            if str(getattr(entry, "extension", "") or "").lower() == ".padxil":
                yield entry


def collect_containers(
    game_root: Path,
    *,
    limit_entries: int,
    progress_every: int = 20000,
) -> tuple[dict[str, PascContainer], dict[str, list[str]], Counter[str], int, int]:
    """Distinct shader bytecode that references the vertex record."""
    containers: dict[str, PascContainer] = {}
    paths: dict[str, list[str]] = defaultdict(list)
    sources: Counter[str] = Counter()
    scanned = 0
    matched = 0
    for entry in iter_shader_entries(game_root):
        if limit_entries and scanned >= limit_entries:
            break
        scanned += 1
        if progress_every and scanned % progress_every == 0:
            print(f"    scanned {scanned:,} shaders, {matched:,} reference the record", flush=True)
        try:
            data, _cached, _source = read_archive_entry_data(entry)
        except Exception:
            continue
        if RECORD_MARKER not in data:
            continue
        parsed = parse_pasc(data)
        if parsed is None:
            continue
        matched += 1
        sources[parsed.source_hlsl] += 1
        containers.setdefault(parsed.digest, parsed)
        paths[parsed.digest].append(str(entry.path).replace("\\", "/"))
    return containers, paths, sources, scanned, matched


def disassemble(dxc: Path, container: bytes, workdir: Path) -> str:
    target = workdir / "shader.dxil"
    target.write_bytes(container)
    result = subprocess.run(
        [str(dxc), "-dumpbin", str(target)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout or ""


# ── Report ───────────────────────────────────────────────────────────

def _byte_verdicts(studies: Sequence[ShaderStudy]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for offset in range(PROVEN_PAC_STRIDE):
        read_by = sum(1 for study in studies if study.byte_read[offset])
        used_by = sum(1 for study in studies if study.byte_used[offset])
        owners = sorted({
            f.name
            for study in studies
            for f in study.struct_fields
            if _field_covers(study, f, offset)
        })
        if used_by:
            verdict = "consumed"
        elif read_by:
            verdict = "fetched but every bit masked away"
        else:
            verdict = "never fetched"
        rows.append(
            {
                "offset": offset,
                "declared_field": owners,
                "shaders_fetching": read_by,
                "shaders_consuming": used_by,
                "verdict": verdict,
            }
        )
    return rows


def _field_covers(study: ShaderStudy, field_value: StructField, offset: int) -> bool:
    ordered = sorted(study.struct_fields, key=lambda value: value.offset)
    for index, candidate in enumerate(ordered):
        if candidate is not field_value:
            continue
        end = ordered[index + 1].offset if index + 1 < len(ordered) else study.struct_size
        return candidate.offset <= offset < end
    return False


# ── Anchoring the shader's arithmetic to real PAC bytes ──────────────

def decode_record_tbn(records: "np.ndarray") -> tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """Decode normal, tangent and handedness exactly as the shipped shader does.

    Transcribed from the DXIL, not inferred:

    * ``normal.x`` from ``_packedNormal`` bits 10-19, ``normal.y`` from bits
      20-29, both as ``v * 2/1023 - 1``;
    * ``normal.z`` as ``sqrt(max(0, 1 - x^2 - y^2))``, negated when bit 30 is set;
    * ``tangent.x`` from bytes 6-7 read as ``int16``, as ``2*|v|/32767 - 1``;
    * ``tangent.y`` from ``_packedNormal`` bits 0-9, same scale as the normal;
    * ``tangent.z`` reconstructed the same way and negated when bytes 6-7 are
      negative, so the sign bit of that lane is the tangent's z sign;
    * bit 31 of ``_packedNormal`` is a separate +/-1, the bitangent handedness.

    The ``max(0, ...)`` is the shader's own clamp, and it is load bearing: 10-bit
    quantisation puts ``x^2 + y^2`` slightly above 1 for a small share of real
    vertices.
    """
    import numpy as np

    count = records.shape[0]
    packed = records[:, 16:20].copy().view(np.uint32).reshape(count).astype(np.uint32)
    tangent_lane = records[:, 6:8].copy().view(np.int16).reshape(count).astype(np.float64)

    normal_x = ((packed >> 10) & 1023).astype(np.float64) * (2.0 / 1023.0) - 1.0
    normal_y = ((packed >> 20) & 1023).astype(np.float64) * (2.0 / 1023.0) - 1.0
    normal_z = np.sqrt(np.maximum(0.0, 1.0 - normal_x * normal_x - normal_y * normal_y))
    normal_z = np.where(((packed >> 30) & 1) != 0, -normal_z, normal_z)

    tangent_x = np.abs(tangent_lane / 32767.0) * 2.0 - 1.0
    tangent_y = (packed & 1023).astype(np.float64) * (2.0 / 1023.0) - 1.0
    tangent_z = np.sqrt(np.maximum(0.0, 1.0 - tangent_x * tangent_x - tangent_y * tangent_y))
    tangent_z = np.where(tangent_lane < 0, -tangent_z, tangent_z)

    handedness = np.where(((packed >> 31) & 1) != 0, -1.0, 1.0)
    return (
        np.stack([normal_x, normal_y, normal_z], axis=1),
        np.stack([tangent_x, tangent_y, tangent_z], axis=1),
        handedness,
    )


def verify_against_pac(game_root: Path, *, assets: int, seed: int) -> dict[str, object]:
    """Check the shader's arithmetic against real records, with a control.

    Orthogonality is the test that matters. Unit length is imposed by the decode
    and proves nothing on its own, but nothing in the arithmetic pushes
    ``dot(T, N)`` towards zero, so it only lands there if bytes 6-7 really do
    pair with that normal. The shuffled control makes that argument explicit by
    breaking the pairing and showing the property collapse.
    """
    import numpy as np

    sys.path.insert(0, str(_REPO_ROOT / "tools"))
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.modding.mesh_pac_topology_builder import (
        _original_records,
        _submesh_is_proven_layout,
        _submesh_is_skinned,
    )
    from pac_parser_corpus_harness import discover_pac_entries

    entries = discover_pac_entries(game_root=game_root, path_contains=("character/model/1_pc",))
    rows: list[dict[str, object]] = []
    total = 0
    orthogonal = 0
    unit_normal = 0
    for entry in entries:
        if len(rows) >= assets:
            break
        try:
            payload, _cached, _source = read_archive_entry_data(entry)
            mesh = parse_mesh(payload, str(entry.path))
        except Exception:
            continue
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
            if not _submesh_is_skinned(submesh) or not _submesh_is_proven_layout(submesh, skinned_required=True):
                continue
            try:
                records = _original_records(submesh, payload)
            except Exception:
                continue
            count = len(records)
            if count < 64:
                continue
            matrix = np.frombuffer(b"".join(records), dtype=np.uint8).reshape(count, PROVEN_PAC_STRIDE)
            normal, tangent, _hand = decode_record_tbn(matrix)
            dots = np.abs(np.sum(normal * tangent, axis=1))
            lengths = np.linalg.norm(normal, axis=1)

            shuffled = matrix.copy()
            order = np.random.default_rng(seed + len(rows)).permutation(count)
            shuffled[:, 6:8] = matrix[order, 6:8]
            control_normal, control_tangent, _c = decode_record_tbn(shuffled)
            control = np.abs(np.sum(control_normal * control_tangent, axis=1))

            total += count
            orthogonal += int((dots < 0.05).sum())
            unit_normal += int((np.abs(lengths - 1.0) < 0.01).sum())
            rows.append(
                {
                    "asset": str(entry.path).replace("\\", "/"),
                    "vertices": count,
                    "median_abs_dot_tangent_normal": round(float(np.median(dots)), 6),
                    "p95_abs_dot": round(float(np.percentile(dots, 95)), 6),
                    "max_abs_dot": round(float(dots.max()), 6),
                    "within_0_05_percent": round(float((dots < 0.05).mean() * 100.0), 4),
                    "unit_normal_percent": round(float((np.abs(lengths - 1.0) < 0.01).mean() * 100.0), 4),
                    "shuffled_control_median_abs_dot": round(float(np.median(control)), 6),
                    "shuffled_control_within_0_05_percent": round(float((control < 0.05).mean() * 100.0), 4),
                }
            )
            break
    return {
        "assets": len(rows),
        "vertices": total,
        "orthogonal_within_0_05_percent": round(orthogonal / total * 100.0, 4) if total else 0.0,
        "unit_normal_percent": round(unit_normal / total * 100.0, 4) if total else 0.0,
        "per_asset": rows,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-root", type=Path, required=True, help="Installed game root, read-only.")
    parser.add_argument("--output", type=Path, default=None, help="Evidence directory under system TEMP.")
    parser.add_argument("--dxc", type=Path, default=None, help="Path to dxc.exe. Located in the Windows SDK by default.")
    parser.add_argument("--max-shaders", type=int, default=400, help="Distinct bytecode blobs to disassemble.")
    parser.add_argument("--limit-entries", type=int, default=0, help="Stop scanning after this many shader entries.")
    parser.add_argument(
        "--verify-assets",
        type=int,
        default=6,
        help="Real PACs to anchor the shader arithmetic against. 0 skips the check.",
    )
    parser.add_argument("--seed", type=int, default=20260813, help="Seed for the shuffled control.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    dxc = locate_dxc(args.dxc)
    if dxc is None:
        print("dxc.exe was not found. Install the Windows SDK or pass --dxc.", file=sys.stderr)
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = args.output or (Path(tempfile.gettempdir()) / "cdmw-pac-shader-consumer" / run_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    print("  scanning the shipped shader cache...", flush=True)
    containers, paths, sources, scanned, matched = collect_containers(
        Path(args.game_root), limit_entries=int(args.limit_entries)
    )
    print(f"  {scanned:,} shaders scanned, {matched:,} reference the record, {len(containers):,} distinct blobs", flush=True)

    studies: list[ShaderStudy] = []
    failures: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="cdmw-dxc-") as raw_workdir:
        workdir = Path(raw_workdir)
        ordered = sorted(containers.items(), key=lambda item: (-len(paths[item[0]]), item[0]))
        for position, (digest, parsed) in enumerate(ordered[: max(0, int(args.max_shaders))]):
            if position and position % 25 == 0:
                print(f"    disassembled {position} shaders", flush=True)
            try:
                text = disassemble(dxc, parsed.container, workdir)
            except Exception as error:
                failures.append({"digest": digest, "error": f"{type(error).__name__}: {error}"})
                continue
            if not text:
                failures.append({"digest": digest, "error": "dxc produced no disassembly"})
                continue
            study = analyse_disassembly(text, digest=digest, source_hlsl=parsed.source_hlsl)
            if study is None:
                failures.append({"digest": digest, "error": "no stride-40 record load found"})
                continue
            study.archive_paths = paths[digest]
            study.occurrences = len(paths[digest])
            studies.append(study)

    layouts = Counter(
        tuple((f.name, f.type_name, f.offset) for f in sorted(study.struct_fields, key=lambda v: v.offset))
        for study in studies
    )

    anchoring: dict[str, object] = {"assets": 0, "skipped": True}
    if int(args.verify_assets) > 0:
        print("  anchoring the shader arithmetic against real records...", flush=True)
        anchoring = verify_against_pac(
            Path(args.game_root), assets=int(args.verify_assets), seed=int(args.seed)
        )
        anchoring["skipped"] = False

    report: dict[str, object] = {
        "report_format": REPORT_FORMAT,
        "phase": STUDY_PHASE,
        "plan": PLAN_PATH,
        "run_id": run_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started, 3),
        "method": {
            "disassembler": str(dxc),
            "bit_usage_analysis": (
                "conservative def-use over the DXIL disassembly; only and/lshr/trunc narrow a "
                "value, everything else consumes the whole operand, so a byte is reported unused "
                "only when the instructions prove it"
            ),
            "scope_limit": (
                "this proves what the GPU is handed and what it does with it, not what the CPU "
                "does before upload"
            ),
        },
        "corpus": {
            "shaders_scanned": scanned,
            "shaders_referencing_record": matched,
            "distinct_bytecode": len(containers),
            "disassembled": len(studies),
            "failures": len(failures),
            "source_files": sources.most_common(20),
        },
        "record_layouts": [
            {
                "occurrences": count,
                "fields": [{"name": name, "type": type_name, "offset": offset} for name, type_name, offset in layout],
            }
            for layout, count in layouts.most_common()
        ],
        "byte_verdicts": _byte_verdicts(studies),
        "pac_anchoring": anchoring,
        "shaders": [study.to_dict() for study in studies],
        "failures": failures[:40],
    }

    report_path = output_dir / "pac-shader-consumer.json"
    _atomic_write_json(report_path, report)

    print(f"\nrun id      : {run_id}")
    print(f"evidence    : {output_dir}")
    print(f"disassembled: {len(studies)} distinct shaders, {len(failures)} failures")
    print(f"layouts     : {len(layouts)} distinct 40-byte record declarations")
    print("\noffset  declared field                          fetched  consumed  verdict")
    for row in report["byte_verdicts"]:  # type: ignore[index]
        names = ",".join(row["declared_field"]) or "-"
        print(
            f"  {row['offset']:>3}  {names[:40]:<40} {row['shaders_fetching']:>7} "
            f"{row['shaders_consuming']:>9}  {row['verdict']}"
        )
    if not anchoring.get("skipped"):
        print(
            f"\nanchoring: {anchoring['vertices']:,} real vertices over {anchoring['assets']} assets, "
            f"{anchoring['orthogonal_within_0_05_percent']}% orthogonal, "
            f"{anchoring['unit_normal_percent']}% unit normals"
        )
        controls = [row["shuffled_control_within_0_05_percent"] for row in anchoring["per_asset"]]  # type: ignore[index]
        if controls:
            print(f"           shuffled control: {min(controls)}% to {max(controls)}% orthogonal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
