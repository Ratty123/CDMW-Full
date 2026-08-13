"""Phase 0 of the PAC vertex channel study: correct the baseline, simulate masks.

Read-only. It opens the installed game archives, pulls proven 40-byte
``pac_slot_u10x6`` LOD0 submeshes, and answers three questions the plan at
``docs/plans/active/pac-vertex-channel-identification-v1.md`` says must be
answered before any format research starts:

1. Which record offsets actually block a derived vertex **under the real bit
   mask**? The earlier histogram counted raw byte differences, so byte 19 was
   credited with differences in the 30 owned normal bits that never blocked
   anything.
2. Do the numbers survive being split by whole asset? 151,927 edges from twelve
   garments are correlated observations, not 151,927 independent samples.
3. If bytes 6-7 and 12-15 were owned, what would that buy at the level a user
   experiences, which is a whole Loop Cut selection or a whole Subdivide
   selection succeeding, not an individual edge?

Nothing here writes to the game directory, and nothing here writes a PAC. The
admission rule is imported from :mod:`cdmw.modding.mesh_pac_topology_builder`
rather than restated, because a study that measured its own private copy of the
rule would measure nothing. The vectorised fast path is checked against that
imported rule on a random sample of every submesh it touches, and the check is
reported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "tools"))

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.domain.mesh.topology import (
    TOPOLOGY_PROTECTED_BYTES_DIVERGE,
    TOPOLOGY_PROVENANCE_VERSION,
    TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED,
    SubmeshTopologyProvenance,
    VertexOrigin,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_mesh
from cdmw.modding.mesh_pac_topology_builder import (
    PROVEN_PAC_STRIDE,
    PacTopologyRebuildBlocked,
    _decoded_live_slots,
    _masked,
    _original_records,
    _submesh_is_proven_layout,
    _submesh_is_skinned,
    derived_skin_row,
    protected_byte_mask,
    topology_rebuild_blockers,
)
from cdmw.models import ArchiveEntry
from pac_parser_corpus_harness import _entry_family, discover_pac_entries

REPORT_FORMAT = "cdmw_pac_channel_study_v1"
STUDY_PHASE = "phase-0"
PLAN_PATH = "docs/plans/active/pac-vertex-channel-identification-v1.md"

#: Six palette slots is the record's capacity, not a policy choice.
MAX_SKIN_INFLUENCES = 6

DEFAULT_DISCOVERY_FAMILIES = (
    "character/model/1_pc/1_phm",
    "character/model/1_pc/2_phw",
    "character/model/1_pc/14_ptm",
    "character/model/1_pc/9_pgm",
    "character/model/1_pc/5_pom",
    "character/model/1_pc/7_pdm",
)
DEFAULT_HOLDOUT_FAMILIES = (
    "character/model/3_npc/1_nhm",
    "character/model/3_npc/2_nhw",
    "character/model/3_npc/14_ntm",
    "character/model/3_npc/5_nom",
)

DEFAULT_RING_LENGTHS = (1, 2, 4, 8, 16, 32, 64)
DEFAULT_FACE_COUNTS = (1, 2, 4, 8, 16, 32, 64)


# ── Candidate ownership masks ────────────────────────────────────────

@dataclass(frozen=True)
class CandidateMask:
    """A proposed move of bits from protected to owned.

    ``clears`` is what the candidate would stop protecting, as
    ``(byte offset, bits)`` pairs. Nothing here authorises owning anything; the
    point is to price each proposal before anyone tries to earn it.
    """

    name: str
    description: str
    clears: tuple[tuple[int, int], ...]

    def applied_to(self, base: bytes) -> bytes:
        mask = bytearray(base)
        for offset, bits in self.clears:
            if 0 <= offset < len(mask):
                mask[offset] &= (~bits) & 0xFF
        return bytes(mask)


def _byte_range_clears(start: int, end: int) -> tuple[tuple[int, int], ...]:
    return tuple((offset, 0xFF) for offset in range(start, end))


_CLEAR_6_7 = _byte_range_clears(6, 8)
_CLEAR_12_15 = _byte_range_clears(12, 16)
_CLEAR_TAIL = _byte_range_clears(34, 40)
#: The two bits of the normal u32 the shipping serializer still protects.
_CLEAR_NORMAL_TOP = ((19, 0xC0),)


def candidate_masks() -> tuple[CandidateMask, ...]:
    return (
        CandidateMask("baseline", "The shipping ownership mask, unchanged.", ()),
        CandidateMask("own_6", "Byte 6 only.", _byte_range_clears(6, 7)),
        CandidateMask("own_7", "Byte 7 only.", _byte_range_clears(7, 8)),
        CandidateMask("own_6_7", "The whole unknown channel at bytes 6-7.", _CLEAR_6_7),
        CandidateMask("own_12_13", "The low half of bytes 12-15, if it is a u16 pair.", _byte_range_clears(12, 14)),
        CandidateMask("own_14_15", "The high half of bytes 12-15, if it is a u16 pair.", _byte_range_clears(14, 16)),
        CandidateMask("own_12_15", "The whole unknown channel at bytes 12-15.", _CLEAR_12_15),
        CandidateMask("own_6_7_12_15", "Both unknown channels, the plan's headline proposal.", _CLEAR_6_7 + _CLEAR_12_15),
        CandidateMask(
            "own_6_7_12_15_normal_top",
            "Both channels plus the two protected bits of the normal u32.",
            _CLEAR_6_7 + _CLEAR_12_15 + _CLEAR_NORMAL_TOP,
        ),
        CandidateMask(
            "own_6_7_12_15_tail",
            "Both channels plus the unknown tail at bytes 34-39.",
            _CLEAR_6_7 + _CLEAR_12_15 + _CLEAR_TAIL,
        ),
        CandidateMask(
            "own_6_7_12_15_normal_top_tail",
            "Every unknown lane at once: the ceiling for protected-byte agreement.",
            _CLEAR_6_7 + _CLEAR_12_15 + _CLEAR_NORMAL_TOP + _CLEAR_TAIL,
        ),
        CandidateMask(
            "own_everything",
            "Nothing protected at all. Isolates the skin-capacity ceiling on its own.",
            tuple((offset, 0xFF) for offset in range(PROVEN_PAC_STRIDE)),
        ),
    )


# ── Source provenance ────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_fingerprints(paths: Iterable[Path], *, hash_contents: bool) -> dict[str, dict[str, object]]:
    fingerprints: dict[str, dict[str, object]] = {}
    for path in sorted({Path(value) for value in paths}, key=lambda value: str(value).casefold()):
        try:
            stat = path.stat()
        except OSError:
            fingerprints[str(path)] = {"exists": False, "size": 0, "mtime_ns": 0, "sha256": ""}
            continue
        row: dict[str, object] = {
            "exists": True,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": "",
        }
        if hash_contents:
            row["sha256"] = _sha256_file(path)
        fingerprints[str(path)] = row
    return fingerprints


def _source_paths(entries: Sequence[ArchiveEntry]) -> list[Path]:
    paths: set[Path] = set()
    for entry in entries:
        for value in (getattr(entry, "pamt_path", None), getattr(entry, "paz_file", None)):
            if value:
                paths.add(Path(str(value)))
    return sorted(paths, key=lambda value: str(value).casefold())


from pac_vertex_channel_sampling import (
    SubmeshStudy,
    _blocker_path_crosscheck,
    _edge_influence_arrays,
    _face_patch,
    _influence_columns,
    _sample_selections,
    _straightest_chain,
    _subdivide_edited_submesh,
    _unique_edges,
    _verify_vectorised_path,
)


def study_submesh(
    submesh: SubMesh,
    submesh_index: int,
    payload: bytes,
    *,
    asset_path: str,
    family: str,
    ring_lengths: Sequence[int],
    face_counts: Sequence[int],
    samples: int,
    agreement_sample: int,
    rng: random.Random,
) -> SubmeshStudy | None:
    if not _submesh_is_skinned(submesh):
        return None
    if not _submesh_is_proven_layout(submesh, skinned_required=True):
        return None
    try:
        records = _original_records(submesh, payload)
    except PacTopologyRebuildBlocked:
        return None

    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    if len(records) != len(vertices) or not faces:
        return None

    edges = _unique_edges(faces, len(vertices))
    if edges.size == 0:
        return None

    record_matrix = np.frombuffer(b"".join(records), dtype=np.uint8).reshape(len(records), PROVEN_PAC_STRIDE)
    diff = record_matrix[edges[:, 0]] ^ record_matrix[edges[:, 1]]

    live, empty = _influence_columns(records)
    fits, unavailable = _edge_influence_arrays(edges, live, empty)

    study = SubmeshStudy(
        asset_path=asset_path,
        family=family,
        submesh_index=submesh_index,
        submesh_name=str(getattr(submesh, "name", "") or ""),
        vertex_count=len(vertices),
        face_count=len(faces),
        edge_count=int(len(edges)),
        edge_diff=diff,
        influence_fits=fits,
        influence_unavailable=unavailable,
    )

    study.agreement_check = _verify_vectorised_path(
        records,
        edges,
        diff,
        fits,
        unavailable,
        protected_byte_mask(skinned=True),
        rng=rng,
        sample_size=agreement_sample,
    )

    positions = np.asarray(vertices, dtype=np.float64)
    _sample_selections(
        study,
        edges,
        faces,
        positions,
        ring_lengths=ring_lengths,
        face_counts=face_counts,
        samples=samples,
        rng=rng,
    )
    return study


# ── Aggregation ──────────────────────────────────────────────────────

def _rate(numerator: int, denominator: int) -> float:
    return (float(numerator) / float(denominator) * 100.0) if denominator else 0.0


def _offset_histogram(studies: Sequence[SubmeshStudy], mask: bytes) -> dict[str, object]:
    mask_array = np.frombuffer(mask, dtype=np.uint8)
    offsets = np.zeros(PROVEN_PAC_STRIDE, dtype=np.int64)
    bits = np.zeros((PROVEN_PAC_STRIDE, 8), dtype=np.int64)
    total = 0
    for study in studies:
        masked = study.edge_diff & mask_array
        offsets += (masked != 0).sum(axis=0, dtype=np.int64)
        for bit in range(8):
            bits[:, bit] += ((masked >> bit) & 1).sum(axis=0, dtype=np.int64)
        total += study.edge_count
    return {
        "edges": int(total),
        "per_offset": [
            {
                "offset": index,
                "mask": int(mask_array[index]),
                "edges": int(offsets[index]),
                "share_percent": round(_rate(int(offsets[index]), total), 4),
            }
            for index in range(PROVEN_PAC_STRIDE)
            if int(mask_array[index]) != 0
        ],
        "per_bit": [
            {
                "offset": index,
                "bit": bit,
                "edges": int(bits[index][bit]),
                "share_percent": round(_rate(int(bits[index][bit]), total), 4),
            }
            for index in range(PROVEN_PAC_STRIDE)
            for bit in range(8)
            if (int(mask_array[index]) >> bit) & 1
        ],
    }


def _candidate_edge_flags(study: SubmeshStudy, mask: bytes) -> np.ndarray:
    mask_array = np.frombuffer(mask, dtype=np.uint8)
    if not mask_array.any():
        return np.ones(study.edge_count, dtype=bool)
    return ~np.any(study.edge_diff & mask_array, axis=1)


def _candidate_report(
    studies: Sequence[SubmeshStudy],
    candidate: CandidateMask,
    base_mask: bytes,
    *,
    ring_lengths: Sequence[int],
    face_counts: Sequence[int],
) -> dict[str, object]:
    mask = candidate.applied_to(base_mask)
    total_edges = 0
    protected_ok = 0
    influence_ok = 0
    combined_ok = 0
    ring_totals: dict[int, list[int]] = {int(length): [0, 0] for length in ring_lengths}
    patch_totals: dict[int, list[int]] = {int(count): [0, 0] for count in face_counts}
    whole_total = 0
    whole_ok = 0
    exhaustive_faces = 0
    exhaustive_faces_ok = 0

    for study in studies:
        protected = _candidate_edge_flags(study, mask)
        eligible = protected & study.influence_fits & ~study.influence_unavailable
        total_edges += study.edge_count
        protected_ok += int(protected.sum())
        influence_ok += int((study.influence_fits & ~study.influence_unavailable).sum())
        combined_ok += int(eligible.sum())
        for length, selections in study.ring_samples.items():
            row = ring_totals.setdefault(int(length), [0, 0])
            for selection in selections:
                row[0] += 1
                if bool(eligible[selection].all()):
                    row[1] += 1
        for count, selections in study.patch_samples.items():
            row = patch_totals.setdefault(int(count), [0, 0])
            for selection in selections:
                row[0] += 1
                if bool(eligible[selection].all()):
                    row[1] += 1
        if study.whole_submesh_edges is not None:
            whole_total += 1
            if bool(eligible.all()):
                whole_ok += 1
        if study.face_edge_rows is not None and study.face_edge_rows.size:
            rows = study.face_edge_rows
            usable = rows[(rows >= 0).all(axis=1)]
            exhaustive_faces += int(usable.shape[0])
            if usable.shape[0]:
                exhaustive_faces_ok += int(eligible[usable].all(axis=1).sum())

    edge_rate = _rate(combined_ok, total_edges)
    return {
        "name": candidate.name,
        "description": candidate.description,
        "cleared": [{"offset": offset, "bits": bits} for offset, bits in candidate.clears],
        "edge_diagnostics": {
            "edges": int(total_edges),
            "protected_agree": int(protected_ok),
            "protected_agree_percent": round(_rate(protected_ok, total_edges), 4),
            "influence_fits": int(influence_ok),
            "influence_fits_percent": round(_rate(influence_ok, total_edges), 4),
            "combined_eligible": int(combined_ok),
            "combined_eligible_percent": round(edge_rate, 4),
        },
        "operations": {
            "loop_cut": [
                {
                    "selected_edges": int(length),
                    "samples": int(ring_totals[int(length)][0]),
                    "admissible": int(ring_totals[int(length)][1]),
                    "admissible_percent": round(_rate(ring_totals[int(length)][1], ring_totals[int(length)][0]), 4),
                    "independence_prediction_percent": round((edge_rate / 100.0) ** int(length) * 100.0, 6),
                }
                for length in sorted(ring_totals)
            ],
            "subdivide_midpoint": [
                {
                    "selected_faces": int(count),
                    "samples": int(patch_totals[int(count)][0]),
                    "admissible": int(patch_totals[int(count)][1]),
                    "admissible_percent": round(_rate(patch_totals[int(count)][1], patch_totals[int(count)][0]), 4),
                }
                for count in sorted(patch_totals)
            ],
            "subdivide_whole_submesh": {
                "submeshes": int(whole_total),
                "admissible": int(whole_ok),
                "admissible_percent": round(_rate(whole_ok, whole_total), 4),
            },
            # Every face in the corpus, not a sample. This is the smallest
            # possible topology-growing operation, so it is the sharpest
            # statement of what the mask buys, free of sampling error.
            "subdivide_single_face_exhaustive": {
                "faces": int(exhaustive_faces),
                "admissible": int(exhaustive_faces_ok),
                "admissible_percent": round(_rate(exhaustive_faces_ok, exhaustive_faces), 4),
            },
        },
    }


# ── Corpus selection ─────────────────────────────────────────────────

@dataclass
class AssetStudy:
    path: str
    family: str
    cohort: str
    payload_sha256: str
    payload_bytes: int
    pamt_path: str
    paz_path: str
    submeshes: list[SubmeshStudy] = field(default_factory=list)
    skipped_submeshes: int = 0
    crosscheck: list[dict[str, object]] = field(default_factory=list)


def _load_asset(
    entry: ArchiveEntry,
    *,
    cohort: str,
    ring_lengths: Sequence[int],
    face_counts: Sequence[int],
    samples: int,
    agreement_sample: int,
    crosscheck_samples: int,
    rng: random.Random,
) -> AssetStudy | None:
    try:
        payload, _cached, _source = read_archive_entry_data(entry)
    except Exception:
        return None
    if not payload or payload[:4] != b"PAR ":
        return None
    try:
        mesh: ParsedMesh = parse_mesh(payload, str(entry.path))
    except Exception:
        return None

    asset_path = str(entry.path or "").replace("\\", "/")
    asset = AssetStudy(
        path=asset_path,
        family=_entry_family(asset_path, depth=4),
        cohort=cohort,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
        pamt_path=str(getattr(entry, "pamt_path", "") or ""),
        paz_path=str(getattr(entry, "paz_file", "") or ""),
    )
    for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        study = study_submesh(
            submesh,
            index,
            payload,
            asset_path=asset_path,
            family=asset.family,
            ring_lengths=ring_lengths,
            face_counts=face_counts,
            samples=samples,
            agreement_sample=agreement_sample,
            rng=rng,
        )
        if study is None:
            asset.skipped_submeshes += 1
            continue
        asset.submeshes.append(study)
    if not asset.submeshes:
        return None

    if crosscheck_samples > 0:
        base_mask = protected_byte_mask(skinned=True)
        eligible_by_submesh = {
            study.submesh_index: (
                _candidate_edge_flags(study, base_mask)
                & study.influence_fits
                & ~study.influence_unavailable
            )
            for study in asset.submeshes
        }
        rows_by_submesh = {
            study.submesh_index: study.face_edge_rows
            for study in asset.submeshes
            if study.face_edge_rows is not None
        }
        asset.crosscheck = _blocker_path_crosscheck(
            mesh,
            payload,
            asset.submeshes,
            eligible_by_submesh,
            rows_by_submesh,
            samples=crosscheck_samples,
            rng=rng,
        )
    return asset


def _entries_by_family(entries: Sequence[ArchiveEntry]) -> dict[str, list[ArchiveEntry]]:
    grouped: dict[str, list[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        grouped[_entry_family(str(entry.path or ""), depth=4)].append(entry)
    for rows in grouped.values():
        rows.sort(key=lambda value: str(value.path or "").casefold())
    return grouped


# ── Report ───────────────────────────────────────────────────────────

def _asset_summary(asset: AssetStudy, base_mask: bytes, candidates: Sequence[CandidateMask],
                   *, ring_lengths: Sequence[int], face_counts: Sequence[int]) -> dict[str, object]:
    return {
        "path": asset.path,
        "family": asset.family,
        "cohort": asset.cohort,
        "payload_sha256": asset.payload_sha256,
        "payload_bytes": asset.payload_bytes,
        "submeshes_measured": len(asset.submeshes),
        "submeshes_skipped": asset.skipped_submeshes,
        "vertices": int(sum(study.vertex_count for study in asset.submeshes)),
        "faces": int(sum(study.face_count for study in asset.submeshes)),
        "edges": int(sum(study.edge_count for study in asset.submeshes)),
        "offset_histogram": _offset_histogram(asset.submeshes, base_mask),
        "candidates": [
            _candidate_report(
                asset.submeshes,
                candidate,
                base_mask,
                ring_lengths=ring_lengths,
                face_counts=face_counts,
            )
            for candidate in candidates
        ],
    }


def _submesh_summary(study: SubmeshStudy, base_mask: bytes) -> dict[str, object]:
    mask_array = np.frombuffer(base_mask, dtype=np.uint8)
    masked = study.edge_diff & mask_array
    protected = ~np.any(masked, axis=1)
    eligible = protected & study.influence_fits & ~study.influence_unavailable
    return {
        "asset": study.asset_path,
        "submesh_index": study.submesh_index,
        "submesh_name": study.submesh_name,
        "vertices": study.vertex_count,
        "faces": study.face_count,
        "edges": study.edge_count,
        "protected_agree_percent": round(_rate(int(protected.sum()), study.edge_count), 4),
        "combined_eligible_percent": round(_rate(int(eligible.sum()), study.edge_count), 4),
        "blocking_offsets": [
            {"offset": index, "edges": int((masked[:, index] != 0).sum())}
            for index in range(PROVEN_PAC_STRIDE)
            if int(mask_array[index]) != 0 and int((masked[:, index] != 0).sum()) > 0
        ],
        "agreement_check": study.agreement_check,
    }


def _leave_one_asset_out(
    assets: Sequence[AssetStudy],
    candidate: CandidateMask,
    base_mask: bytes,
    *,
    ring_lengths: Sequence[int],
    face_counts: Sequence[int],
) -> list[dict[str, object]]:
    """Pooled results with each asset removed in turn.

    One large garment dominating a pooled total is the pseudoreplication failure
    the plan names, so the report shows what the number becomes without each
    asset rather than asserting the pool is safe.
    """
    rows: list[dict[str, object]] = []
    for excluded in assets:
        remaining = [study for asset in assets if asset is not excluded for study in asset.submeshes]
        if not remaining:
            continue
        report = _candidate_report(
            remaining, candidate, base_mask, ring_lengths=ring_lengths, face_counts=face_counts
        )
        rows.append(
            {
                "excluded_asset": excluded.path,
                "edges": report["edge_diagnostics"]["edges"],
                "combined_eligible_percent": report["edge_diagnostics"]["combined_eligible_percent"],
                "loop_cut": report["operations"]["loop_cut"],
                "subdivide_midpoint": report["operations"]["subdivide_midpoint"],
            }
        )
    return rows


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    temporary.replace(path)


# ── Entry point ──────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-root", type=Path, default=None, help="Installed game root to read read-only.")
    parser.add_argument("--pamt", type=Path, action="append", default=[], help="Explicit PAMT index to read.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Evidence directory. Defaults to %%TEMP%%/cdmw-pac-channel-study/<run-id>.",
    )
    parser.add_argument("--discovery-family", action="append", default=[], help="Family prefix for the discovery cohort.")
    parser.add_argument("--holdout-family", action="append", default=[], help="Family prefix for the blind holdout cohort.")
    parser.add_argument("--assets-per-family", type=int, default=2, help="Proven assets to take from each family.")
    parser.add_argument("--family-scan-limit", type=int, default=40, help="Entries to try per family before giving up.")
    parser.add_argument("--samples", type=int, default=200, help="Selection samples per size per submesh.")
    parser.add_argument("--agreement-sample", type=int, default=64, help="Edges per submesh checked against the shipping rule.")
    parser.add_argument(
        "--crosscheck-samples",
        type=int,
        default=4,
        help="Selections per submesh put through topology_rebuild_blockers end to end. 0 disables.",
    )
    parser.add_argument("--ring-lengths", default=",".join(str(value) for value in DEFAULT_RING_LENGTHS))
    parser.add_argument("--face-counts", default=",".join(str(value) for value in DEFAULT_FACE_COUNTS))
    parser.add_argument("--seed", type=int, default=20260813, help="Deterministic sampling seed.")
    parser.add_argument(
        "--skip-archive-hash",
        action="store_true",
        help="Record size and mtime only. The run then proves less; the report says so.",
    )
    return parser


def _int_list(value: str) -> tuple[int, ...]:
    return tuple(sorted({int(part) for part in str(value).split(",") if part.strip()}))


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = args.output or (Path(__import__("tempfile").gettempdir()) / "cdmw-pac-channel-study" / run_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    ring_lengths = _int_list(args.ring_lengths)
    face_counts = _int_list(args.face_counts)
    discovery_families = tuple(args.discovery_family) or DEFAULT_DISCOVERY_FAMILIES
    holdout_families = tuple(args.holdout_family) or DEFAULT_HOLDOUT_FAMILIES

    started = time.time()
    entries = discover_pac_entries(
        game_root=args.game_root,
        pamt_paths=tuple(args.pamt),
        path_contains=("character/model",),
    )
    grouped = _entries_by_family(entries)

    hash_contents = not args.skip_archive_hash
    rng = random.Random(int(args.seed))

    # Fingerprint every archive the scan could reach before anything is read, so
    # the after-comparison covers files this run opened and rejected as well as
    # the ones it kept.
    scan_windows: list[tuple[str, ArchiveEntry]] = []
    for cohort, families in (("discovery", discovery_families), ("holdout", holdout_families)):
        for family in families:
            for entry in grouped.get(family, ())[: max(1, int(args.family_scan_limit))]:
                scan_windows.append((cohort, entry))
    if not scan_windows:
        print("No archive entries matched the requested families.", file=sys.stderr)
        return 2
    source_paths = _source_paths([entry for _cohort, entry in scan_windows])
    before = _archive_fingerprints(source_paths, hash_contents=hash_contents)

    assets: list[AssetStudy] = []
    taken_per_family: dict[tuple[str, str], int] = defaultdict(int)
    for cohort, entry in scan_windows:
        key = (cohort, _entry_family(str(entry.path or ""), depth=4))
        if taken_per_family[key] >= int(args.assets_per_family):
            continue
        asset = _load_asset(
            entry,
            cohort=cohort,
            ring_lengths=ring_lengths,
            face_counts=face_counts,
            samples=int(args.samples),
            agreement_sample=int(args.agreement_sample),
            crosscheck_samples=int(args.crosscheck_samples),
            rng=rng,
        )
        if asset is None:
            continue
        assets.append(asset)
        taken_per_family[key] += 1

    after = _archive_fingerprints(source_paths, hash_contents=hash_contents)
    unchanged = before == after

    if not assets:
        print("No proven skinned pac_slot_u10x6 assets were found for the requested families.", file=sys.stderr)
        return 2

    base_mask = protected_byte_mask(skinned=True)
    masks = candidate_masks()
    discovery = [asset for asset in assets if asset.cohort == "discovery"]
    holdout = [asset for asset in assets if asset.cohort == "holdout"]
    discovery_studies = [study for asset in discovery for study in asset.submeshes]
    holdout_studies = [study for asset in holdout for study in asset.submeshes]
    all_studies = discovery_studies + holdout_studies

    agreement_failures = [
        study.agreement_check
        for study in all_studies
        if not bool(study.agreement_check.get("agreed", False))
    ]

    headline = next(mask for mask in masks if mask.name == "own_6_7_12_15")

    crosscheck_rows = [row for asset in assets for row in asset.crosscheck]
    crosscheck_errors = [row for row in crosscheck_rows if "error" in row]
    crosscheck_verdicts = [row for row in crosscheck_rows if "error" not in row]
    crosscheck_disagreements = [row for row in crosscheck_verdicts if not row["agreed"]]
    other_blockers: dict[str, int] = defaultdict(int)
    for row in crosscheck_verdicts:
        for code in row["gate_blockers"]:  # type: ignore[union-attr]
            if code not in (TOPOLOGY_PROTECTED_BYTES_DIVERGE, TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED):
                other_blockers[str(code)] += 1
    crosscheck_summary = {
        "selections": len(crosscheck_verdicts),
        "errors": len(crosscheck_errors),
        "agreed": len(crosscheck_verdicts) - len(crosscheck_disagreements),
        "disagreements": crosscheck_disagreements[:20],
        "gate_admitted": sum(1 for row in crosscheck_verdicts if not row["gate_derivation_blocked"]),
        "gate_refused": sum(1 for row in crosscheck_verdicts if row["gate_derivation_blocked"]),
        "both_branches_exercised": (
            any(not row["gate_derivation_blocked"] for row in crosscheck_verdicts)
            and any(row["gate_derivation_blocked"] for row in crosscheck_verdicts)
        ),
        "other_blockers_seen": dict(sorted(other_blockers.items())),
        "sample_errors": crosscheck_errors[:5],
    }

    report: dict[str, object] = {
        "report_format": REPORT_FORMAT,
        "phase": STUDY_PHASE,
        "plan": PLAN_PATH,
        "run_id": run_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started, 3),
        "arguments": {
            "game_root": str(args.game_root) if args.game_root else "",
            "discovery_families": list(discovery_families),
            "holdout_families": list(holdout_families),
            "assets_per_family": int(args.assets_per_family),
            "samples_per_size": int(args.samples),
            "ring_lengths": list(ring_lengths),
            "face_counts": list(face_counts),
            "seed": int(args.seed),
            "archive_hash_mode": "sha256" if hash_contents else "size_and_mtime_only",
        },
        "method": {
            "admission_rule": "cdmw.modding.mesh_pac_topology_builder (imported, not restated)",
            "protected_mask_hex": base_mask.hex(),
            "loop_cut_selection_model": (
                "straightest-continuation edge chain of the requested length; a proxy for a user's "
                "loop selection, because the editor has no ring-propagation command and the native "
                "operation consumes whatever edge set was selected"
            ),
            "subdivide_selection_model": (
                "breadth-first connected face patch of the requested size; every edge of every "
                "selected face gets a midpoint, so all of them must be admissible"
            ),
            "edge_rates_are_diagnostics_only": True,
        },
        "source_provenance": {
            "archives_before": before,
            "archives_after": after,
            "archives_unchanged": bool(unchanged),
            "assets": [
                {
                    "path": asset.path,
                    "cohort": asset.cohort,
                    "payload_sha256": asset.payload_sha256,
                    "payload_bytes": asset.payload_bytes,
                    "pamt_path": asset.pamt_path,
                    "paz_path": asset.paz_path,
                }
                for asset in assets
            ],
        },
        "verification": {
            "vectorised_path_agrees_with_shipping_rule": not agreement_failures,
            "submeshes_checked": len(all_studies),
            "edges_checked": int(sum(int(study.agreement_check.get("sampled_edges", 0)) for study in all_studies)),
            "failures": agreement_failures,
            "blocker_path_crosscheck": crosscheck_summary,
        },
        "corpus": {
            "assets": len(assets),
            "discovery_assets": len(discovery),
            "holdout_assets": len(holdout),
            "submeshes": len(all_studies),
            "edges": int(sum(study.edge_count for study in all_studies)),
            "discovery_edges": int(sum(study.edge_count for study in discovery_studies)),
            "holdout_edges": int(sum(study.edge_count for study in holdout_studies)),
        },
        "offset_histogram": {
            "note": (
                "Recomputed under the real bit mask. Byte 19 counts only its two protected bits, "
                "so owned-bit differences in the normal u32 no longer inflate it."
            ),
            "pooled": _offset_histogram(all_studies, base_mask),
            "discovery": _offset_histogram(discovery_studies, base_mask),
            "holdout": _offset_histogram(holdout_studies, base_mask),
        },
        "candidates": {
            "pooled": [
                _candidate_report(all_studies, mask, base_mask, ring_lengths=ring_lengths, face_counts=face_counts)
                for mask in masks
            ],
            "discovery": [
                _candidate_report(discovery_studies, mask, base_mask, ring_lengths=ring_lengths, face_counts=face_counts)
                for mask in masks
            ],
            "holdout": [
                _candidate_report(holdout_studies, mask, base_mask, ring_lengths=ring_lengths, face_counts=face_counts)
                for mask in masks
            ],
        },
        "leave_one_asset_out": {
            "candidate": headline.name,
            "rows": _leave_one_asset_out(
                assets, headline, base_mask, ring_lengths=ring_lengths, face_counts=face_counts
            ),
        },
        "per_asset": [
            _asset_summary(asset, base_mask, masks, ring_lengths=ring_lengths, face_counts=face_counts)
            for asset in assets
        ],
        "per_submesh": [_submesh_summary(study, base_mask) for study in all_studies],
    }

    report_path = output_dir / "pac-vertex-channel-study.json"
    _atomic_write_json(report_path, report)

    print(f"run id            : {run_id}")
    print(f"evidence          : {output_dir}")
    print(f"assets            : {len(discovery)} discovery, {len(holdout)} holdout")
    print(f"submeshes / edges : {len(all_studies)} / {report['corpus']['edges']:,}")
    print(f"archives unchanged: {unchanged}")
    print(f"vector path agrees: {not agreement_failures}")
    print(
        f"blocker crosscheck: {crosscheck_summary['agreed']}/{crosscheck_summary['selections']} agreed, "
        f"{crosscheck_summary['gate_admitted']} admitted / {crosscheck_summary['gate_refused']} refused, "
        f"other blockers {crosscheck_summary['other_blockers_seen'] or 'none'}"
    )
    for row in report["candidates"]["pooled"]:  # type: ignore[index]
        diagnostics = row["edge_diagnostics"]
        loop = {entry["selected_edges"]: entry["admissible_percent"] for entry in row["operations"]["loop_cut"]}
        print(
            f"  {row['name']:<32} edge {diagnostics['combined_eligible_percent']:>8.4f}%   "
            f"loop cut 1/4/16 {loop.get(1, 0.0):>8.4f}% {loop.get(4, 0.0):>8.4f}% {loop.get(16, 0.0):>8.4f}%"
        )
    if not unchanged:
        print("SOURCE ARCHIVES CHANGED DURING THE RUN", file=sys.stderr)
        return 3
    if agreement_failures:
        print("VECTORISED PATH DISAGREED WITH THE SHIPPING ADMISSION RULE", file=sys.stderr)
        return 4
    if crosscheck_disagreements:
        print("SIMULATED ELIGIBILITY DISAGREED WITH topology_rebuild_blockers", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
