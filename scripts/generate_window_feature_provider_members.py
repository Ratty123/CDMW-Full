from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.util
import inspect
import json
import os
import sys
import textwrap
import zlib
from importlib import import_module
from pathlib import Path
from types import FunctionType
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_PATH = REPO_ROOT / "cdmw" / "ui" / "shell" / "window_feature_providers.py"
OUTPUT_PATH = REPO_ROOT / "cdmw" / "ui" / "shell" / "window_feature_provider_members.py"
_SKIPPED_MEMBERS = {
    "__annotations__",
    "__dict__",
    "__doc__",
    "__init__",
    "__module__",
    "__slots__",
    "__weakref__",
}


def _provider_declarations() -> tuple[tuple[str, str], ...]:
    tree = ast.parse(PROVIDERS_PATH.read_text(encoding="utf-8"), filename=str(PROVIDERS_PATH))
    declaration_source = ""
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if not any(isinstance(target, ast.Name) and target.id == "_PROVIDER_DECLARATIONS" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            declaration_source = value.value
            break
    if not declaration_source:
        raise RuntimeError(f"Missing _PROVIDER_DECLARATIONS in {PROVIDERS_PATH}")
    declarations: list[tuple[str, str]] = []
    for node in ast.parse(declaration_source).body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        declarations.extend((node.module, alias.name) for alias in node.names)
    return tuple(dict.fromkeys(declarations))


def _method_arity(descriptor: object) -> int | None:
    drop_bound_parameter = False
    target = descriptor
    if isinstance(descriptor, (classmethod, staticmethod)):
        target = descriptor.__func__
        drop_bound_parameter = isinstance(descriptor, classmethod)
    elif isinstance(descriptor, FunctionType):
        drop_bound_parameter = True
    if not inspect.isroutine(target):
        return None
    try:
        parameters = list(inspect.signature(target).parameters.values())
    except (TypeError, ValueError):
        return -1
    if drop_bound_parameter and parameters:
        parameters = parameters[1:]
    if any(parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return -1
    return sum(
        parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in parameters
    )


def _file_digest(path: Path) -> str:
    """Digest the source, not its line endings.

    `.gitattributes` sets `text=auto`, so these files are LF in the repository
    and CRLF in a Windows checkout -- and a working tree can hold either, since
    git only rewrites a file when it next touches it. A raw byte digest then
    reports a perfectly current manifest as stale: generated from LF working
    copies it passed here and failed on the runner's CRLF checkout, which is a
    property of the checkout rather than of the providers it is meant to track.
    """

    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _payload_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def build_provider_metadata() -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    payload: dict[str, dict[str, object]] = {}
    source_paths = {PROVIDERS_PATH, Path(__file__).resolve()}
    for module_name, class_name in _provider_declarations():
        provider = getattr(import_module(module_name), class_name)
        names: list[str] = []
        methods: dict[str, int] = {}
        for owner in provider.__mro__:
            if owner is object:
                continue
            source_path = inspect.getsourcefile(owner)
            if source_path:
                resolved = Path(source_path).resolve()
                if resolved.is_relative_to(REPO_ROOT):
                    source_paths.add(resolved)
            for name, descriptor in owner.__dict__.items():
                if name in _SKIPPED_MEMBERS or (name.startswith("__") and name.endswith("__")):
                    continue
                if name in names:
                    continue
                names.append(name)
                arity = _method_arity(descriptor)
                if arity is not None:
                    methods[name] = arity
        payload[f"{module_name}\0{class_name}"] = {"names": names, "methods": methods}
    source_hashes = {
        path.relative_to(REPO_ROOT).as_posix(): _file_digest(path)
        for path in sorted(source_paths)
    }
    return payload, source_hashes


def build_provider_payload() -> dict[str, dict[str, object]]:
    return build_provider_metadata()[0]


def render_provider_module(payload: Mapping[str, object], source_hashes: Mapping[str, str]) -> str:
    raw_json = _payload_bytes(payload)
    encoded = base64.b85encode(zlib.compress(raw_json, level=9)).decode("ascii")
    chunks = "\n".join(f"    {chunk!r}" for chunk in textwrap.wrap(encoded, width=112))
    source_hash_lines = "\n".join(
        f"    {path!r}: {digest!r}," for path, digest in sorted(source_hashes.items())
    )
    payload_digest = hashlib.sha256(raw_json).hexdigest()
    return f'''from __future__ import annotations

import base64
import json
import zlib


# Generated by scripts/generate_window_feature_provider_members.py.
PROVIDER_PAYLOAD_SHA256 = {payload_digest!r}
PROVIDER_SOURCE_HASHES = {{
{source_hash_lines}
}}
_PROVIDER_MEMBERS_B85 = (
{chunks}
)
_RAW_PROVIDER_MEMBERS = json.loads(
    zlib.decompress(base64.b85decode("".join(_PROVIDER_MEMBERS_B85))).decode("utf-8")
)
PROVIDER_MEMBERS: dict[tuple[str, str], tuple[str, ...]] = {{
    tuple(key.split("\\0", 1)): tuple(value["names"])
    for key, value in _RAW_PROVIDER_MEMBERS.items()
}}
PROVIDER_METHOD_ARITIES: dict[tuple[str, str], dict[str, int]] = {{
    tuple(key.split("\\0", 1)): dict(value["methods"])
    for key, value in _RAW_PROVIDER_MEMBERS.items()
}}
del _PROVIDER_MEMBERS_B85, _RAW_PROVIDER_MEMBERS


__all__ = ["PROVIDER_MEMBERS", "PROVIDER_METHOD_ARITIES"]
'''


def check_generated_module() -> bool:
    if not OUTPUT_PATH.is_file():
        return False
    spec = importlib.util.spec_from_file_location("_cdmw_generated_provider_members_check", OUTPUT_PATH)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        payload = {
            f"{module_name}\0{class_name}": {
                "names": list(names),
                "methods": module.PROVIDER_METHOD_ARITIES[(module_name, class_name)],
            }
            for (module_name, class_name), names in module.PROVIDER_MEMBERS.items()
        }
        if hashlib.sha256(_payload_bytes(payload)).hexdigest() != module.PROVIDER_PAYLOAD_SHA256:
            return False
        if not module.PROVIDER_SOURCE_HASHES:
            return False
        return all(
            (REPO_ROOT / relative_path).is_file()
            and _file_digest(REPO_ROOT / relative_path) == digest
            for relative_path, digest in module.PROVIDER_SOURCE_HASHES.items()
        )
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate lazy MainWindow provider member metadata.")
    check_group = parser.add_mutually_exclusive_group()
    check_group.add_argument("--check", action="store_true", help="Quickly fail when provider sources changed.")
    check_group.add_argument("--full-check", action="store_true", help="Rebuild metadata in memory and compare it.")
    args = parser.parse_args()
    if args.check:
        if not check_generated_module():
            print(f"Stale generated provider metadata: {OUTPUT_PATH}", file=sys.stderr)
            return 1
        return 0
    payload, source_hashes = build_provider_metadata()
    rendered = render_provider_module(payload, source_hashes)
    if args.full_check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            print(f"Stale generated provider metadata: {OUTPUT_PATH}", file=sys.stderr)
            return 1
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
