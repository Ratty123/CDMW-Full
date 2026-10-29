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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "cdmw/ui/shell/error_reference_data.py"
EXCLUDED = {"cdmw/ui/shell/error_reference.py", "cdmw/ui/shell/error_reference_data.py"}


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
    if any(part in path for part in ("archive_backend_client", "archive_catalogue_service", "WorkerServer", "/archive_browser/controller", "/archive_browser/filter_workers", "/archive_browser/scan_lifecycle", "remote_finder_warmup")):
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


def collect_reference(root: Path = ROOT) -> list[dict]:
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


def serialized(rows: list[dict]) -> str:
    # A Python data module is packaged through the ordinary import graph; the
    # installed application never scans its sources or needs repository files.
    return '"""Generated diagnostic inventory; run scripts/generate_error_reference.py --write."""\n\nERROR_REFERENCE = ' + json.dumps(rows, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rows = collect_reference()
    expected = serialized(rows)
    if args.write:
        OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    elif not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
        print("Error code reference is stale; run scripts/generate_error_reference.py --write.")
        return 1
    print(f"Error code reference: {len(rows)} code/family entries, {len({row['code'] for row in rows})} distinct identifiers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
