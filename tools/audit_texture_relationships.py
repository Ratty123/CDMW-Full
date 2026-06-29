from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


_DDS_REF_RE = re.compile(r'<ResourceReferencePath_ITexture\b[^>]*(?:_path|value)\s*=\s*"([^"]*)"', re.IGNORECASE)
_PARAM_NAME_RE = re.compile(r'<MaterialParameter\w+\b[^>]*(?:_name|Name)\s*=\s*"([^"]*)"', re.IGNORECASE)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit texture relationships in an extracted archive tree.")
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--family-root", type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--md-out", required=True, type=Path)
    args = parser.parse_args(argv)

    report = build_report(args.archive_root, args.game_root, args.family_root)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"counts": report["counts"]}, sort_keys=True))
    return 0


def build_report(archive_root: Path, game_root: Path, family_root: Path | None = None) -> dict[str, object]:
    roots = [archive_root]
    if family_root is not None:
        roots.append(family_root)
    pac_files = _files(roots, ".pac")
    pac_xml_files = _files([archive_root], ".pac_xml")
    dds_files = _files([archive_root], ".dds")
    tex_files = _files([archive_root, game_root], ".tex")
    dds_by_path = {_rel(path, archive_root).lower(): path for path in dds_files}
    dds_by_basename: dict[str, list[Path]] = {}
    for path in dds_files:
        dds_by_basename.setdefault(path.name.lower(), []).append(path)

    pairs, orphan_pac_xml, pac_without = _pac_pairs(pac_files, pac_xml_files, archive_root)
    sidecar_refs, malformed_refs, risky = _sidecar_refs(pac_xml_files, archive_root, dds_by_path, dds_by_basename)
    family_companions, family_examples = _family_companions(family_root) if family_root is not None else ([], [])
    dds_suffixes, dds_formats = _dds_facts(dds_files)
    ambiguous = [{"basename": name, "count": len(paths)} for name, paths in sorted(dds_by_basename.items()) if len(paths) > 1]

    counts = {
        "dds_files": len(dds_files),
        "pac_files": len(pac_files),
        "pac_xml_files": len(pac_xml_files),
        "pac_with_pac_xml": len(pairs),
        "pac_without_pac_xml": len(pac_without),
        "pac_xml_without_pac": len(orphan_pac_xml),
        "sidecar_dds_refs_total": len(sidecar_refs),
        "sidecar_dds_refs_resolved": sum(1 for row in sidecar_refs if row["status"] == "resolved_exact"),
        "sidecar_dds_refs_missing": sum(1 for row in sidecar_refs if row["status"] == "missing"),
        "sidecar_dds_refs_ambiguous_basename": sum(1 for row in sidecar_refs if row["status"] == "ambiguous_basename"),
        "malformed_refs": malformed_refs,
        "ambiguous_dds_basenames": len(ambiguous),
        "family_hkx_companions": sum(len(row["hkx"]) for row in family_companions),
        "family_pab_companions": sum(len(row["pab"]) for row in family_companions),
        "family_prefab_companions": sum(len(row["prefab"]) for row in family_companions),
        "tex_files": len(tex_files),
    }
    return {
        "schema": "cdmw_texture_relationship_audit_v1",
        "counts": counts,
        "dds_suffixes": dds_suffixes,
        "dds_formats": dict(dds_formats),
        "pac_pac_xml_pairs": pairs,
        "orphan_pac_xml": orphan_pac_xml,
        "ambiguous_basenames": ambiguous,
        "sidecar_dds_refs": sidecar_refs,
        "family_companions": family_companions,
        "family_examples": family_examples,
        "top_risky_parameter_patterns": _risky_patterns(risky),
    }


def _files(roots: Sequence[Path], suffix: str) -> list[Path]:
    result: list[Path] = []
    for root in roots:
        if root is not None and root.is_dir():
            result.extend(path for path in root.rglob(f"*{suffix}") if path.is_file())
    return sorted(result)


def _pac_pairs(pac_files: Sequence[Path], pac_xml_files: Sequence[Path], root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], list[Path]]:
    xml_by_model_rel = {
        _rel(path, root).replace("/modelproperty/", "/model/").removesuffix(".pac_xml") + ".pac": path
        for path in pac_xml_files
    }
    pac_rels = {_rel(path, root): path for path in pac_files if root in path.parents}
    pairs = [{"pac": rel, "pac_xml": _rel(xml_by_model_rel[rel], root), "status": "exact"} for rel in sorted(pac_rels) if rel in xml_by_model_rel]
    paired_xml = {row["pac_xml"] for row in pairs}
    orphan = [{"path": _rel(path, root)} for path in pac_xml_files if _rel(path, root) not in paired_xml]
    missing = [path for rel, path in pac_rels.items() if rel not in xml_by_model_rel]
    missing.extend(path for path in pac_files if root not in path.parents)
    return pairs, orphan, missing


def _sidecar_refs(
    pac_xml_files: Sequence[Path],
    root: Path,
    dds_by_path: Mapping[str, Path],
    dds_by_basename: Mapping[str, Sequence[Path]],
) -> tuple[list[dict[str, object]], int, Counter[str]]:
    rows: list[dict[str, object]] = []
    malformed = 0
    risky: Counter[str] = Counter()
    for path in pac_xml_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        names = _PARAM_NAME_RE.findall(text) or ["(unknown)"]
        for ref in _DDS_REF_RE.findall(text):
            normalized = ref.replace("\\", "/").strip()
            if not normalized or " " in normalized or not normalized.lower().endswith(".dds"):
                malformed += 1
                continue
            key = normalized.lower()
            matches = dds_by_basename.get(Path(normalized).name.lower(), ())
            if key in dds_by_path:
                status = "resolved_exact"
            elif len(matches) > 1:
                status = "ambiguous_basename"
            else:
                status = "missing"
            rows.append({"sidecar": _rel(path, root), "dds_reference": normalized, "status": status})
            if status != "resolved_exact":
                risky[names[0]] += 1
    return rows, malformed, risky


def _dds_facts(paths: Sequence[Path]) -> tuple[dict[str, dict[str, object]], Counter[str]]:
    suffixes: dict[str, dict[str, object]] = {}
    formats: Counter[str] = Counter()
    for path in paths:
        fmt = _dds_format(path)
        formats[fmt] += 1
        suffix = _suffix(path)
        bucket = suffixes.setdefault(suffix, {"count": 0, "formats": {}})
        bucket["count"] = int(bucket["count"]) + 1
        bucket_formats = bucket["formats"]
        bucket_formats[fmt] = int(bucket_formats.get(fmt, 0)) + 1
    return suffixes, formats


def _family_companions(root: Path) -> tuple[list[dict[str, object]], list[dict[str, int]]]:
    pacs = _files([root], ".pac")
    rows: list[dict[str, object]] = []
    examples: list[dict[str, int]] = []
    all_files = [path for path in root.rglob("*") if path.is_file()]
    for pac in pacs:
        stem = pac.stem.lower()
        hkx = [{"path": _rel(path, root)} for path in all_files if path.suffix.lower() == ".hkx" and path.stem.lower() == stem]
        pab = [{"path": _rel(path, root)} for path in all_files if path.suffix.lower() == ".pab" and path.stem.lower() == stem]
        prefab = [{"path": _rel(path, root)} for path in all_files if path.suffix.lower() == ".prefab" and path.stem.lower().startswith(stem)]
        rows.append({"pac": _rel(pac, root), "hkx": hkx, "pab": pab, "prefab": prefab})
        examples.append({"dds": 0, "pab": len(pab)})
    return rows, examples


def _dds_format(path: Path) -> str:
    data = path.read_bytes()[:128]
    if data.startswith(b"DDS ") and data[84:88] == b"DXT1":
        return "BC1_UNORM"
    return "UNKNOWN"


def _suffix(path: Path) -> str:
    stem = path.stem.lower()
    return "_" + stem.rsplit("_", 1)[-1] if "_" in stem else ""


def _risky_patterns(counter: Counter[str]) -> list[dict[str, object]]:
    return [{"parameter_name": name, "risk_refs": count} for name, count in counter.most_common()]


def _markdown(report: Mapping[str, object]) -> str:
    return "# Texture Relationship Audit\n\n## Top Risky Parameter Patterns\n\n" + "\n".join(
        f"- {row['parameter_name']}: {row['risk_refs']}" for row in report.get("top_risky_parameter_patterns", [])
    ) + "\n"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
