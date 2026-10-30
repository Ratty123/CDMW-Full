"""Snapshot CDMW diagnostic identifiers for the shared Help/Wiki reference.

No project code is imported or executed. Literal diagnostic factories, code
fields, the Mesh Editor registry, topology blockers and the archive worker's
exception classifier are the owning sources. Runtime-dependent identifiers
remain searchable templates; free-text exceptions are not invented as codes.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.error_reference_scan import scan_sources, _literal_part
OUTPUT = ROOT / "cdmw/ui/shell/error_reference_data.py"
EXCLUDED = {"cdmw/ui/shell/error_reference.py", "cdmw/ui/shell/error_reference_data.py", "cdmw/ui/shell/error_reference_guidance.py"}


def _text(node: ast.AST | None, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id, "")
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "MeshEditorErrorCode":
        return node.attr
    if isinstance(node, ast.JoinedStr):
        return "".join(str(value.value) if isinstance(value, ast.Constant) else "{" + ast.unparse(value.value) + "}" for value in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _text(node.left, constants) + _text(node.right, constants)
    return ""


def _group(path: str, code: str) -> str:
    if code.startswith(("MAT_", "VIEW_", "EDIT_", "WRITEBACK_", "PACKAGE_", "RENDERER_")):
        return "mesh_runtime"
    if code.startswith("TOPOLOGY_"):
        return "topology"
    if path.startswith(('native/', 'tools/rust_mesh_lab/')) or 'texture_native' in path or 'placement_studio' in path:
        return 'native_tools'
    if any(part in path for part in ("archive_backend_client", "archive_catalogue_service", "dotnet_archive_backend", "/archive_browser/controller", "/archive_browser/filter_workers", "/archive_browser/scan_lifecycle", "remote_finder_warmup")):
        return "archive"
    if "/new_item/" in path:
        return "new_item"
    if "texture_pipeline/inspection" in path:
        return "dds"
    if "virtual_" in path or "independent_item_isolation" in path:
        return "independent"
    if any(part in path for part in ("material", "external_model_audit", "mesh_rust_authoring")):
        return "materials"
    if "/rendering/" in path:
        return "capture"
    if any(part in path for part in ("panel_state", "tab_reports", "mesh_service_uv", "mesh_service_rigging", "ui_state_reducer")):
        return "panels"
    return "mesh_validation"


def collect_registered_reference(root: Path = ROOT) -> list[dict]:
    trees = {}
    constants = {}
    signatures = {
        "ArchiveBackendError": ["code", "message", "detail"],
        "MeshPanelUnavailableError": ["code", "message"],
        "TopologyProvenanceError": ["code", "message"],
    }
    locals_by_path = {}
    for path in sorted((root / "cdmw").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative in EXCLUDED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        trees[relative] = tree
        local = locals_by_path[relative] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper() and target.id == node.value.value:
                        constants[target.id] = node.value.value
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [arg.arg for arg in node.args.args if arg.arg != "self"]
                all_names = names + [arg.arg for arg in node.args.kwonlyargs]
                if "code" in all_names and any(key in all_names for key in ("message", "detail", "severity")):
                    local[node.name] = names
                    if node.name == "_issue":
                        signatures[node.name] = names
            if isinstance(node, ast.ClassDef):
                names = [entry.target.id for entry in node.body if isinstance(entry, ast.AnnAssign) and isinstance(entry.target, ast.Name)]
                if "code" in names and any(key in names for key in ("message", "detail", "severity")):
                    signatures[node.name] = names

    rows = {}
    def add(path, code, message="", severity=""):
        if not code or " " in code:
            return
        key = (_group(path, code), code)
        row = rows.setdefault(key, {"group": key[0], "code": code, "messages": set(), "sources": set(), "severity": set()})
        if message:
            row["messages"].add(" ".join(message.split()))
        row["sources"].add(path)
        if severity:
            row["severity"].add(severity)

    for path, tree in trees.items():
        local = locals_by_path[path]
        for node in ast.walk(tree):
            fields = {}
            if isinstance(node, ast.Dict):
                fields = {_text(key, constants): value for key, value in zip(node.keys, node.values)}
            elif isinstance(node, ast.Call):
                fields = {key.arg: key.value for key in node.keywords if key.arg}
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                # Attribute calls must resolve to this class's diagnostic method;
                # never interpret ordinary list.append or set.add as a factory.
                sig = local.get(name, signatures.get(name, [])) if isinstance(node.func, ast.Name) else local.get(name, []) if name.startswith("_") else []
                fields.update(zip(sig, node.args))
            code = _text(fields.get("code") or fields.get("error_code") or fields.get("recovery_error_code"), constants)
            message = _text(fields.get("message") or fields.get("detail") or fields.get("title") or fields.get("reason"), constants)
            severity = _text(fields.get("severity") or fields.get("status"), constants)
            if not (code and any(key in fields for key in ('native_name', 'english_name', 'translations', 'language'))):
                add(path, code, message, severity)
            if isinstance(node, ast.ClassDef) and node.name == "MeshEditorErrorCode":
                for entry in node.body:
                    if isinstance(entry, ast.Assign):
                        add(path, _text(entry.value, constants))
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "TOPOLOGY_BLOCKER_CODES" for target in node.targets):
                for value in node.value.elts:
                    add(path, _text(value, constants))

    worker = "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    text = (root / worker).read_text(encoding="utf-8-sig")
    for code, message in re.findall(r'WorkerProtocol\.Failure\(request,\s*"([\w_]+)",\s*"([^"]+)"', text):
        add(worker, code, message)
    classifier = text.split("var code = exception switch", 1)[1].split("return new WorkerError", 1)[0]
    for code in re.findall(r'=> "([\w_]+)"', classifier):
        add(worker, code)
    # Defaults used when the lower-level diagnostic has no fixed identifier.
    add("cdmw/services/archive_catalogue_service.py", "unknown_error")
    add("cdmw/ui/shell/archive_backend_client.py", "protocol_failure")
    add("cdmw/domain/mesh/export_validation.py", "sidecar_warning")
    add("cdmw/services/mesh_rust_authoring.py", "material_synthesis_fallback")
    return [{**row, "messages": sorted(row["messages"]), "sources": sorted(row["sources"]), "severity": sorted(row["severity"])} for _, row in sorted(rows.items())]


def message_area(path: str) -> str:
    lower = path.lower()
    rules = (
        ('formats', ('hkx', 'prefab', 'papr', 'paloc', 'format_explorer', 'archive_binary', 'crimson_formats')),
        ('placement', ('placement_studio', 'paa_motion', 'placement')),
        ('independent', ('virtual_', 'independent_item')),
        ('items', ('new_item', 'item_composer', 'item_spec', 'item_effect')),
        ('translations', ('translation_studio', 'translation_provider', 'translation_service')),
        ('packages', ('mod_package', 'archive_patch', 'archive_mutation', 'restore', 'rollback', 'recovery', 'mod_management')),
        ('materials', ('material',)),
        ('textures', ('texture', 'dds', 'ncnn', 'chainner')),
        ('archive', ('archive', 'pamt', 'paz')),
        ('capture', ('capture', 'renderdoc', 'research', 'test_run', 'compare_preview')),
        ('mesh', ('mesh', 'preview', 'refit', 'model', 'skeleton')),
        ('settings', ('/app/', 'setting', 'startup', 'localization', 'profile', 'theme', 'workspace')),
    )
    return next((area for area, words in rules if any(word in lower for word in words)), 'other')


def recovery_kind(text: str) -> str:
    value = text.lower().replace('_', ' ')
    if re.search(r'showing raw stored bytes|^decoded preview failed:|^raw bytes$|^string scan truncated', value):
        return 'preview'
    rules = (
        ('cancelled', r'cancelled|canceled|cancellation|user.*cancel'),
        ('authentication', r'api key|credential|unauthorized|unauthorised|\b401\b|\b403\b|\b429\b|rate limit|quota'),
        ('permission', r'access denied|permission|read.only (?:file|folder|directory)|write.protect'),
        ('locked', r'file.*lock|sharing violation|file.*in use|another process|already running|\bbusy\b'),
        ('space', r'disk.*full|no space|out of memory|memory allocation|not enough memory'),
        ('helper', r'(?:helper|executable|dll|shared library|dynamic library|runtime).*(?:missing|unavailable|not found|incompatible)|(?:missing|unavailable).*(?:helper|executable|dll|shared library|dynamic library)'),
        ('timeout', r'timeout|timed out|time limit|deadline'),
        ('recovery', r'backup|rollback|restore point|recovery material|confirmation required|safety refusal'),
        ('integrity', r'hash|sha.?256|checksum|signature.*mismatch|provenance|identity.*(?:mismatch|invalid|missing)|protected bytes'),
        ('stale', r'\bstale\b|revision|generation|source.*changed|changed.*source|out.of.order|replayed'),
        ('conflict', r'already exists|overwrite|conflicting|duplicate|overlap'),
        ('network', r'http|network|remote service|server error|socket.*(?:connect|send|receive)|certificate|connection.*(?:refus|reset|fail|timed)'),
        ('gpu', r'd3d|direct3d|wgpu|gpu|shader.*(?:fail|error|invalid)|device.*(?:lost|remov|fail)|surface.*(?:fail|error)'),
        ('configuration', r'protocol|schema|version.*(?:mismatch|unsupported|invalid)|configuration|setting'),
        ('unsupported', r'unsupported|not supported|not implemented|read.only|not yet|cannot.*safely|not rebuildable'),
        ('limits', r'exceed|too (?:large|many|small|long)|limit|overflow|out.of.(?:bounds|range)|outside.*(?:range|buffer|payload|source)|capacity'),
        ('empty', r'\bempty\b|nothing to|no (?:usable|valid|matching|selected|edited|pending|prepared|supported)|selection.*required'),
        ('missing', r'\bmissing\b|not found|does not exist|no such file|unavailable|could not (?:find|locate)|required.*(?:file|path)'),
        ('format', r'header|magic|truncated|compressed|decompress|encoding|utf.8|decode|parse|malformed|corrupt|payload|unexpected end|short read|trailing bytes|incomplete|could not read'),
        ('write', r'write|writing|publish|publication|save.*fail|export.*fail|output.*fail'),
        ('input', r'invalid|must|requires?|expected|mismatch|range|negative|finite|select|not a |not an |cannot|blocked|refus|reject'),
    )
    return next((key for key, pattern in rules if re.search(pattern, value)), 'internal')


@lru_cache(maxsize=2)
def collect_library(root: Path = ROOT) -> dict:
    registered = collect_registered_reference(root)
    by_code = {(row['group'], row['code']): row for row in registered}
    emissions, coverage = scan_sources(root)
    messages = {}
    dynamic = {}
    for item in emissions:
        if item.code:
            key = (_group(item.path, item.code), item.code)
            row = by_code.setdefault(key, {'group': key[0], 'code': item.code, 'messages': [], 'sources': [], 'severity': []})
            if item.path not in row['sources']:
                row['sources'].append(item.path)
            if item.text and _literal_part(item.text) and item.text != item.code and item.text not in row['messages']:
                row['messages'].append(item.text)
        area = message_area(item.path)
        if not _literal_part(item.text) or item.kind == 'native_handoff':
            dynamic.setdefault(area, set()).add(item.path)
            continue
        if item.code and item.text == item.code:
            continue
        key = (area, item.text)
        row = messages.setdefault(key, {'area': area, 'message': item.text, 'recovery': recovery_kind(item.text), 'sources': {}})
        row['sources'].setdefault(item.path, item.line)
    return {
        'ERROR_REFERENCE': [{**row, 'messages': sorted(set(row['messages'])), 'sources': sorted(set(row['sources'])), 'recovery': recovery_kind(row['code'] + ' ' + ' '.join(row['messages']))} for _, row in sorted(by_code.items())],
        'MESSAGE_REFERENCE': [{**row, 'sources': dict(sorted(row['sources'].items()))} for _, row in sorted(messages.items())],
        'DYNAMIC_REFERENCE': {area: sorted(paths) for area, paths in sorted(dynamic.items())},
        'SOURCE_COVERAGE': coverage,
    }


def collect_reference(root: Path = ROOT) -> list[dict]:
    return collect_library(root)['ERROR_REFERENCE']


def serialized(library: dict) -> str:
    # A Python data module is packaged through the ordinary import graph; the
    # installed application never scans its sources or needs repository files.
    return '"""Generated diagnostic inventory; run scripts/generate_error_reference.py --write."""\n\n' + '\n\n'.join(name + ' = ' + json.dumps(rows, ensure_ascii=False, indent=2) for name, rows in library.items()) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    library = collect_library()
    rows = library['ERROR_REFERENCE']
    expected = serialized(library)
    if args.write:
        OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    elif not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
        print("Error code reference is stale; run scripts/generate_error_reference.py --write.")
        return 1
    print(f"Error code reference: {len(rows)} code/family entries, {len({row['code'] for row in rows})} distinct identifiers.")
    print(f"Message reference: {len(library['MESSAGE_REFERENCE'])} patterns; {len(library['SOURCE_COVERAGE'])} source files audited; dynamic handoffs in {len(library['DYNAMIC_REFERENCE'])} areas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
