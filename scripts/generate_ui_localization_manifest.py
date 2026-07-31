"""Generate or verify the packaged CDMW-owned UI source-string manifest."""

from __future__ import annotations

import argparse
import ast
import bisect
import html
import json
import re
import string
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "cdmw" / "resources" / "localization"
MANIFEST_PATH = RESOURCE_ROOT / "source_manifest.json"
ENGLISH_CATALOG_PATH = RESOURCE_ROOT / "en.json"
EXCLUSIONS_PATH = ROOT / "scripts" / "ui_localization_exclusions.json"
DOTNET_LOCALIZATION_PATH = (
    ROOT
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "ExperimentForm.UiLocalization.cs"
)
DOTNET_KEYS_BEGIN = "    // BEGIN GENERATED UI LOCALIZATION KEYS"
DOTNET_KEYS_END = "    // END GENERATED UI LOCALIZATION KEYS"

PYTHON_SOURCE_ROOTS = (
    ROOT / "cdmw" / "app",
    ROOT / "cdmw" / "services",
    ROOT / "cdmw" / "ui",
    ROOT / "cdmw" / "workers",
    ROOT / "tools" / "placement_studio",
    ROOT / "tools" / "format_explorer",
    ROOT / "tools" / "translation_studio",
)
CSHARP_SOURCE_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"
MANUAL_SOURCE_KEYS = frozenset(
    {
        "Abort",
        "Apply",
        "AES",
        "ChaCha20",
        "Cancel",
        "Close",
        "Context",
        "Discard",
        "Help",
        "Hint",
        "ICE",
        "Ignore",
        "LZ4",
        "No",
        "No to All",
        "No placement chain",
        "OK",
        "Open",
        "Partial",
        "Path hint",
        "QuickLZ",
        "Reset",
        "Restore Defaults",
        "Retry",
        "Save",
        "Save All",
        "Updating app colors and preview panes...",
        "Yes",
        "Yes to All",
        "Zlib",
        "animation",
        "authoritative",
        "auto-fixed",
        "cloth",
        "context",
        "cross_package",
        "derived_family_heuristic",
        "derived_same_stem",
        "exact_path",
        "full",
        "info",
        "lod",
        "manual",
        "material_sidecar",
        "mesh",
        "metadata",
        "model ok",
        "partial",
        "path_normalized",
        "pending",
        "recommended",
        "requires-manual-review",
        "required",
        "resolved",
        "selected",
        "skeleton",
        "structural",
        "texture",
        "warning",
        "{count} files",
        # Associated Assets group headers. They are rendered from
        # `cdmw.domain.archives.association_vocabulary.ASSET_FAMILY_GROUP_ORDER`
        # so the panel, the dialog and the graph builder cannot disagree about
        # which groups exist, and `cdmw/domain` is not a scanned source root.
        # Without these the headers would quietly fall back to English.
        "Animation / Motion",
        "Attachment / Placement",
        "Audio / Video",
        "Item Icons",
        "Material",
        "MeshInfo",
        "Other",
        "Physics / HKX",
        "Prefab / Metadata",
        "Selected Model",
        "Skeleton / Rig",
        "Textures",
    }
)

_MULTI_VALUE_SINKS = {
    "addItems",
    "setHeaderLabels",
    "setHorizontalHeaderLabels",
    "setVerticalHeaderLabels",
}
_PYTHON_SINKS = {
    "QAction",
    "QCheckBox",
    "QCommandLinkButton",
    "QGroupBox",
    "QLabel",
    "QMenu",
    "QListWidgetItem",
    "QPushButton",
    "QRadioButton",
    "QProgressDialog",
    "QTableWidgetItem",
    "QTreeWidgetItem",
    "AlignmentD3D11LoadingRecoveryAction",
    "AlignmentD3D11HostReadyState",
    "AlignmentD3D11StatusPresentation",
    "ArchiveModelTextureReference",
    "ArchivePreviewResult",
    "AssetAuthoringHelperSpec",
    "EmptyStateTreeWidget",
    "Guide",
    "MeshImportSetupSelection",
    "MeshImportSupplementalFileSpec",
    "MeshEditorAction",
    "ModelPreviewData",
    "ProviderPreset",
    "PreviewHelpPresentation",
    "ReplacementAssetProfile",
    "ResearchTreeColumnSpec",
    "Section",
    "SourcePartContextActionSpec",
    "SourcePartsPendingPresentation",
    "Term",
    "ArchiveBackendError",
    "EditError",
    "FileNotFoundError",
    "PermissionError",
    "RuntimeError",
    "RunCancelled",
    "TypeError",
    "ValueError",
    "ArchiveWorkflowDependenciesUnavailable",
    "addAction",
    "add",
    "addButton",
    "addItem",
    "addItems",
    "addMenu",
    "addRow",
    "add_row",
    "addSection",
    "addTab",
    "appendHtml",
    "appendLog",
    "appendPlainText",
    "append_archive_log",
    "append_log",
    "clear_model",
    "clear_preview",
    "critical",
    "drawText",
    "emit",
    "getItem",
    "getOpenFileName",
    "getOpenFileNames",
    "getExistingDirectory",
    "getColor",
    "getDouble",
    "getInt",
    "getFont",
    "getMultiLineText",
    "getSaveFileName",
    "getText",
    "information",
    "insertTab",
    "insertHtml",
    "insertPlainText",
    "log",
    "on_log",
    "progress",
    "question",
    "raise_if_cancelled",
    "report",
    "setDescription",
    "setAccessibleDescription",
    "setAccessibleName",
    "setHeaderData",
    "setData",
    "setHeaderLabels",
    "setHtml",
    "setLabelText",
    "setDetailedText",
    "setFormat",
    "setInformativeText",
    "setItemData",
    "setItemText",
    "setIconText",
    "setPlaceholderText",
    "setPlainText",
    "setPrefix",
    "setStatusMessage",
    "setStatusTip",
    "setSubTitle",
    "setSuffix",
    "setTabToolTip",
    "setTabText",
    "setText",
    "setTitle",
    "setToolTip",
    "setVerticalHeaderLabels",
    "setWhatsThis",
    "setWindowTitle",
    "setHorizontalHeaderLabels",
    "set_status_message",
    "set_empty_state",
    "showText",
    "showMessage",
    "start",
    "tr",
    "pump_startup_splash",
    "set_detail",
    "update_pyinstaller_boot_splash",
    "write_startup_splash_command",
    "write_startup_splash_payload",
    "_update_startup_splash",
    "_append_log",
    "_log",
    "_send_dotnet_command_result",
    "_set_action_button_state",
    "_set_alignment_d3d11_progress",
    "_set_archive_cache_health",
    "_set_archive_load_progress",
    "_set_dotnet_status",
    "_set_inline_preview_status",
    "_set_status",
    "_add_titled_help_header",
    "_add_candidate",
    "_adjustment_param_state",
    "_queue_appearance_apply_step",
    "_push_geometry_undo_snapshot",
    "_set_archive_list_status",
    "_set_archive_warmup_overlay",
    "_set_embedded_dotnet_preview_loading",
    "_set_mesh_edit_row_visible",
    "_simple_morph_command",
    "_push_history",
    "texture_context_kv_row",
    "translate_active_ui_text",
    "_write_crash_report",
    "warning",
}
_FILE_DIALOG_SINKS = {
    "getExistingDirectory",
    "getOpenFileName",
    "getOpenFileNames",
    "getSaveFileName",
}
_PYTHON_FRAMEWORK_UI_RETURN_METHODS = frozenset({"data", "headerData"})
_CSHARP_WRAPPER_ARG_INDEXES: dict[str, tuple[int, ...] | None] = {
    "AddField": (1,),
    "AddHelpSection": (1, 2),
    "AddPresentationViewButton": (1,),
    "AddSection": (1,),
    "AddToolRailPageButton": (3, 5),
    "AddToolRailToolButton": (3, 5),
    "ApplyOverlayColorButtonStyle": (1,),
    "CameraButton": (0,),
    "ChooseOverlayColor": (0,),
    "CommandButton": (0,),
    "ConfigureCheckBox": (1,),
    "ConfigureMorphStatusLabel": (1,),
    "CreateDockHeader": (1,),
    "CreateMorphCompactCard": (0, 1),
    "GizmoButton": (0,),
    "LabeledControl": (0,),
    "NavigationChip": (0, 1),
    "OverlayColorButton": (0,),
    "PickPartColour": (1,),
    "SetHelpText": (1,),
    "StyledActionButton": (0,),
    "StyledButton": (0,),
    "ToolButton": (0,),
    "ToolCheckBox": (0,),
}
_CSHARP_CROSS_FILE_UI_RETURN_METHODS = frozenset(
    {
        # Produced in ExperimentForm.Protocol.cs and assigned to _fpsLabel.Text
        # by the timer in the Runtime partial.
        "RendererMetricsText",
    }
)
_HTML_TAG_RE = re.compile(r"(<[^>]+>)")
_HTML_NON_TEXT_BLOCK_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_WHITESPACE_RE = re.compile(r"\s+")
_CSHARP_UI_SINK_RE = re.compile(
    r"(?:"
    r"\bText\s*=|\.Text\s*=|SetToolTip\s*\(|MessageBox\.Show\s*\(|"
    r"StatusRequested\?\.Invoke\s*\(|"
    r"Set(?:Status|Hint)\s*\(|SetAccessible|"
    r"Accessible(?:Name|Description)\s*=|ToolTipText\s*=|"
    r"new\s+(?:Button|Label|CheckBox|RadioButton|GroupBox|ToolStripMenuItem|"
    r"ToolStripButton|TabPage|ComboBoxItem)\s*[\(\{]|"
    r"\.Items\.Add\s*\(|\.Items\.AddRange\s*\(|\.TabPages\.Add\s*\("
    r")"
)
_CSHARP_MAX_SINK_REGION_CHARS = 8_000


@dataclass(frozen=True, slots=True)
class _CSharpString:
    value: str
    start: int
    end: int
    line: int


@dataclass(frozen=True, slots=True)
class _CSharpMethod:
    name: str
    start: int
    end: int


def _looks_like_translatable_text(value: str) -> bool:
    text = _WHITESPACE_RE.sub(" ", str(value or "").strip())
    if len(text) < 1 or len(text) > 4_000 or not re.search(r"[A-Za-z]", text):
        return False
    if text.startswith(("http://", "https://", "file://", "#", ".", "*.")):
        return False
    if text.startswith("--"):
        return False
    if ";;" in text or "\\" in text:
        return False
    if "/" in text and " " not in text and "{" not in text:
        return False
    if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", text):
        return False
    if re.search(r"\b(?:rgba?|hsla?)\s*\(", text, re.IGNORECASE):
        return False
    if re.search(
        r"\b(?:border|padding|margin|background|font-size|min-height|text-align)\s*:",
        text,
        re.IGNORECASE,
    ):
        return False
    if re.fullmatch(r"[{}()[\].,;:+\\/<>=_*|#%$@!?0-9 -]+", text):
        return False
    if re.fullmatch(
        r"(?:\{[A-Za-z_][A-Za-z0-9_]*(?:![^}:]+)?(?::[^}]+)?\}\s*)+",
        text,
    ):
        return False
    return True


def _html_segments(value: str) -> tuple[str, ...]:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return (text,) if _looks_like_translatable_text(text) else ()
    text = _HTML_NON_TEXT_BLOCK_RE.sub("", text)
    segments: set[str] = set()
    for segment in _HTML_TAG_RE.split(text):
        if not segment or segment.startswith("<"):
            continue
        normalized = _WHITESPACE_RE.sub(
            " ",
            html.unescape(segment).strip(),
        )
        if _looks_like_translatable_text(normalized):
            segments.add(normalized)
    return tuple(sorted(segments))


def _python_call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _normalized_format_template(value: str) -> str:
    try:
        parsed = tuple(string.Formatter().parse(str(value)))
    except ValueError:
        return str(value)
    output: list[str] = []
    positional_index = 0
    for literal, field, format_spec, conversion in parsed:
        output.append(literal.replace("{", "{{").replace("}", "}}"))
        if field is None:
            continue
        field_name = str(field)
        if not field_name or field_name.isdigit():
            field_name = f"value_{positional_index}"
            positional_index += 1
        rendered = "{" + field_name
        if conversion:
            rendered += f"!{conversion}"
        if format_spec:
            rendered += f":{format_spec}"
        output.append(rendered + "}")
    return "".join(output)


def _python_source_template(
    node: ast.AST,
    *,
    placeholder_index: int = 0,
    allow_placeholder: bool = False,
) -> tuple[str, int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, placeholder_index
    if isinstance(node, ast.JoinedStr):
        output: list[str] = []
        current_index = placeholder_index
        for value in node.values:
            if isinstance(value, ast.Constant):
                output.append(str(value.value))
                continue
            output.append(f"{{value_{current_index}}}")
            current_index += 1
        return "".join(output), current_index
    if (
        isinstance(node, ast.Call)
        and _python_call_name(node) in {"translate", "translate_rendered"}
        and node.args
    ):
        return _python_source_template(
            node.args[0],
            placeholder_index=placeholder_index,
            allow_placeholder=allow_placeholder,
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and isinstance(node.func.value, ast.Constant)
        and isinstance(node.func.value.value, str)
    ):
        return (
            _normalized_format_template(node.func.value.value),
            placeholder_index,
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, next_index = _python_source_template(
            node.left,
            placeholder_index=placeholder_index,
            allow_placeholder=True,
        )
        right, next_index = _python_source_template(
            node.right,
            placeholder_index=next_index,
            allow_placeholder=True,
        )
        return left + right, next_index
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mod)
        and isinstance(node.left, ast.Constant)
        and isinstance(node.left.value, str)
    ):
        raw = str(node.left.value)
        current_index = placeholder_index

        def replacement(match: re.Match[str]) -> str:
            nonlocal current_index
            if match.group(0) == "%%":
                return "%"
            result = f"{{value_{current_index}}}"
            current_index += 1
            return result

        return (
            re.sub(
                r"%%|%(?:\([^)]+\))?[-+#0 ]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa]",
                replacement,
                raw,
            ),
            current_index,
        )
    if allow_placeholder and isinstance(
        node,
        (
            ast.Attribute,
            ast.Call,
            ast.Name,
            ast.Subscript,
        ),
    ):
        return f"{{value_{placeholder_index}}}", placeholder_index + 1
    return "", placeholder_index


def _python_source_value(node: ast.AST) -> str:
    value, _next_index = _python_source_template(node)
    return value


def _python_candidate_nodes(call: ast.Call, sink: str) -> Iterable[ast.AST]:
    if sink in {"information", "warning", "critical", "question"}:
        indexes = (1, 2)
    elif sink in {"getOpenFileName", "getOpenFileNames", "getSaveFileName"}:
        indexes = (1, 3)
    elif sink == "getExistingDirectory":
        indexes = (1,)
    elif sink in {"getText", "getMultiLineText"}:
        indexes = (1, 2)
    elif sink == "getItem":
        indexes = (1, 2, 3)
    elif sink == "addTab":
        indexes = (1,)
    elif sink == "insertTab":
        indexes = (2,)
    elif sink in _MULTI_VALUE_SINKS:
        indexes = tuple(range(len(call.args)))
    else:
        indexes = tuple(range(len(call.args)))
    for index in indexes:
        if index >= len(call.args):
            continue
        candidate = call.args[index]
        if isinstance(candidate, (ast.List, ast.Tuple)):
            yield from candidate.elts
        else:
            yield candidate
    for keyword in call.keywords:
        if keyword.arg is not None:
            yield keyword.value
    if sink in {"write_startup_splash_command", "write_startup_splash_payload"}:
        for keyword in call.keywords:
            if keyword.arg in {"detail", "message_key"}:
                yield keyword.value


def _python_file_filter_nodes(call: ast.Call, sink: str) -> Iterable[ast.AST]:
    if sink not in _FILE_DIALOG_SINKS or sink == "getExistingDirectory":
        return
    if len(call.args) > 3:
        yield call.args[3]
    for keyword in call.keywords:
        if keyword.arg == "filter":
            yield keyword.value


def _file_filter_labels(value: str) -> tuple[str, ...]:
    labels: list[str] = []
    for raw_part in str(value or "").split(";;"):
        part = raw_part.strip()
        match = re.fullmatch(r"(?P<label>.*?)\s*\([^()]*\)\s*", part)
        label = (match.group("label") if match else "").strip()
        if _looks_like_translatable_text(label):
            labels.append(label)
    return tuple(labels)


def _python_parameters(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, ...]:
    arguments = definition.args
    parameters = tuple(
        argument.arg
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        )
    )
    if parameters and parameters[0] in {"self", "cls"}:
        return parameters[1:]
    return parameters


def _walk_python_function_body(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterable[ast.AST]:
    stack = list(reversed(definition.body))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _python_argument_for_index(
    call: ast.Call,
    index: int,
    signatures: Iterable[tuple[str, ...]],
) -> Iterable[ast.AST]:
    if index < len(call.args):
        yield call.args[index]
        return
    keyword_map = {
        keyword.arg: keyword.value
        for keyword in call.keywords
        if keyword.arg is not None
    }
    for signature in signatures:
        if index < len(signature) and signature[index] in keyword_map:
            yield keyword_map[signature[index]]


def _python_wrapper_candidates(
    call: ast.Call,
    indexes: Iterable[int],
    signatures: Iterable[tuple[str, ...]],
) -> Iterable[ast.AST]:
    for index in sorted(set(indexes)):
        yield from _python_argument_for_index(call, index, signatures)


def _python_assigned_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
    ):
        return (f"{target.value.id}.{target.attr}",)
    if isinstance(target, (ast.List, ast.Tuple)):
        return tuple(
            name
            for element in target.elts
            for name in _python_assigned_names(element)
        )
    return ()


def _python_local_assignments(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, tuple[ast.AST, ...]]:
    assignments: dict[str, list[ast.AST]] = defaultdict(list)
    for node in _walk_python_function_body(definition):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _python_assigned_names(target):
                    assignments[name].append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            for name in _python_assigned_names(node.target):
                assignments[name].append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            for name in _python_assigned_names(node.target):
                assignments[name].append(node.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, (ast.Name, ast.Attribute))
            and node.func.attr in {"add", "append", "extend", "insert"}
        ):
            target_names = _python_assigned_names(node.func.value)
            if not target_names:
                continue
            if node.func.attr in {"add", "append"} and node.args:
                values = (node.args[0],)
            elif node.func.attr == "insert" and len(node.args) > 1:
                values = (node.args[1],)
            elif node.func.attr == "extend" and node.args:
                extension = node.args[0]
                values = (
                    tuple(extension.elts)
                    if isinstance(extension, (ast.List, ast.Set, ast.Tuple))
                    else (extension,)
                )
            else:
                values = ()
            for name in target_names:
                assignments[name].extend(values)

    assignment_view = {
        name: tuple(values)
        for name, values in assignments.items()
    }

    def iterable_rows(
        node: ast.AST,
        seen: frozenset[int] = frozenset(),
    ) -> tuple[ast.AST, ...]:
        node_id = id(node)
        if node_id in seen:
            return ()
        next_seen = seen | {node_id}
        rows: list[ast.AST] = []
        for expanded in _python_expand_local_value(node, assignment_view):
            if isinstance(expanded, (ast.List, ast.Set, ast.Tuple)):
                rows.extend(expanded.elts)
            elif isinstance(expanded, ast.Dict):
                rows.extend(key for key in expanded.keys if key is not None)
            elif (
                isinstance(expanded, ast.Call)
                and _python_call_name(expanded)
                in {"enumerate", "reversed", "sorted", "tuple", "list"}
                and expanded.args
            ):
                nested = iterable_rows(
                    expanded.args[0],
                    next_seen | {id(expanded)},
                )
                if _python_call_name(expanded) == "enumerate":
                    rows.extend(
                        ast.Tuple(
                            elts=[ast.Constant(index), value],
                            ctx=ast.Load(),
                        )
                        for index, value in enumerate(nested)
                    )
                else:
                    rows.extend(nested)
            elif (
                isinstance(expanded, ast.Call)
                and _python_call_name(expanded) == "zip"
                and expanded.args
            ):
                columns = tuple(
                    iterable_rows(
                        argument,
                        next_seen | {id(expanded)},
                    )
                    for argument in expanded.args
                )
                if columns and all(columns):
                    rows.extend(
                        ast.Tuple(
                            elts=list(values),
                            ctx=ast.Load(),
                        )
                        for values in zip(*columns)
                    )
            elif (
                isinstance(expanded, ast.Call)
                and isinstance(expanded.func, ast.Attribute)
                and expanded.func.attr == "items"
            ):
                for mapping in _python_expand_local_value(
                    expanded.func.value,
                    assignment_view,
                ):
                    if not isinstance(mapping, ast.Dict):
                        continue
                    rows.extend(
                        ast.Tuple(
                            elts=[key, value],
                            ctx=ast.Load(),
                        )
                        for key, value in zip(mapping.keys, mapping.values)
                        if key is not None
                    )
        return tuple(rows)

    for node in _walk_python_function_body(definition):
        if not isinstance(node, (ast.For, ast.comprehension)):
            continue
        target = node.target
        for row in iterable_rows(node.iter):
            if isinstance(target, (ast.List, ast.Tuple)) and isinstance(
                row,
                (ast.List, ast.Tuple),
            ):
                for target_element, value in zip(target.elts, row.elts):
                    for name in _python_assigned_names(target_element):
                        assignments[name].append(value)
            else:
                for name in _python_assigned_names(target):
                    assignments[name].append(row)
    return {
        name: tuple(values)
        for name, values in assignments.items()
    }


def _python_module_assignments(tree: ast.Module) -> dict[str, tuple[ast.AST, ...]]:
    assignments: dict[str, list[ast.AST]] = defaultdict(list)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _python_assigned_names(target):
                    assignments[name].append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            for name in _python_assigned_names(node.target):
                assignments[name].append(node.value)
    return {
        name: tuple(values)
        for name, values in assignments.items()
    }


def _python_reference_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return _python_reference_name(node.value)
    return ""


def _python_expand_local_value(
    node: ast.AST,
    assignments: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> Iterable[ast.AST]:
    yield node
    reference_name = _python_reference_name(node)
    if not reference_name or reference_name in seen:
        return
    for value in assignments.get(reference_name, ()):
        yield from _python_expand_local_value(
            value,
            assignments,
            seen=seen | {reference_name},
        )


def _python_ui_return_methods(
    definitions: Iterable[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef, tuple[str, ...]]
    ],
    wrapper_indexes: dict[str, set[int]],
    signatures: dict[str, set[tuple[str, ...]]],
) -> set[str]:
    definitions = tuple(definitions)
    known_methods = {definition.name for definition, _parameters in definitions}
    ui_return_methods: set[str] = set(_PYTHON_FRAMEWORK_UI_RETURN_METHODS)

    def add_called_helpers(
        candidates: Iterable[ast.AST],
        assignments: dict[str, tuple[ast.AST, ...]],
    ) -> bool:
        before = len(ui_return_methods)
        stack = list(candidates)
        seen_references: set[str] = set()
        while stack:
            candidate = stack.pop()
            for expanded in _python_expand_local_value(candidate, assignments):
                for descendant in ast.walk(expanded):
                    if isinstance(descendant, ast.Call):
                        called = _python_call_name(descendant)
                        if called in known_methods:
                            ui_return_methods.add(called)
                    # An f-string hides its parts behind names: `title, text =
                    # helper()` then `setText(f"{title}: {text}")` reaches the
                    # sink with no Call anywhere under the candidate node. The
                    # rendered translation pass resolves such a line as template
                    # plus arguments, so the helper's strings are user-visible
                    # exactly as if returned to the sink directly. Follow only
                    # names interpolated into f-strings; following every
                    # reference under a candidate drags identifiers and log
                    # fragments into the manifest.
                    if not isinstance(descendant, ast.FormattedValue):
                        continue
                    reference = _python_reference_name(descendant.value)
                    if (
                        reference
                        and reference not in seen_references
                        and reference in assignments
                    ):
                        seen_references.add(reference)
                        stack.extend(assignments[reference])
        return len(ui_return_methods) != before

    for definition, _parameters in definitions:
        assignments = _python_local_assignments(definition)
        for node in _walk_python_function_body(definition):
            if not isinstance(node, ast.Call):
                continue
            sink = _python_call_name(node)
            if sink in _PYTHON_SINKS:
                candidates = _python_candidate_nodes(node, sink)
            elif sink in wrapper_indexes:
                candidates = _python_wrapper_candidates(
                    node,
                    wrapper_indexes[sink],
                    signatures.get(sink, ()),
                )
            else:
                continue
            add_called_helpers(candidates, assignments)

    changed = True
    while changed:
        changed = False
        for definition, _parameters in definitions:
            if definition.name not in ui_return_methods:
                continue
            assignments = _python_local_assignments(definition)
            for node in _walk_python_function_body(definition):
                if isinstance(node, ast.Return) and node.value is not None:
                    changed = add_called_helpers((node.value,), assignments) or changed
    return ui_return_methods


def _infer_python_ui_constructors(
    trees: Iterable[tuple[Path, ast.Module]],
    wrapper_indexes: dict[str, set[int]],
    signatures: dict[str, set[tuple[str, ...]]],
) -> None:
    constructors: list[
        tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, tuple[str, ...]]
    ] = []
    for _path, tree in trees:
        for class_node in (
            node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ):
            for node in class_node.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "__init__"
                ):
                    parameters = _python_parameters(node)
                    constructors.append((class_node.name, node, parameters))
                    signatures[class_node.name].add(parameters)
                    break

    changed = True
    while changed:
        changed = False
        for class_name, definition, parameters in constructors:
            parameter_indexes = {
                parameter: index for index, parameter in enumerate(parameters)
            }
            discovered: set[int] = set()
            for node in _walk_python_function_body(definition):
                if not isinstance(node, ast.Call):
                    continue
                sink = _python_call_name(node)
                if sink in _PYTHON_SINKS:
                    candidates = tuple(_python_candidate_nodes(node, sink))
                elif sink in wrapper_indexes:
                    candidates = tuple(
                        _python_wrapper_candidates(
                            node,
                            wrapper_indexes[sink],
                            signatures.get(sink, ()),
                        )
                    )
                else:
                    continue
                for candidate in candidates:
                    for descendant in ast.walk(candidate):
                        if (
                            isinstance(descendant, ast.Name)
                            and descendant.id in parameter_indexes
                        ):
                            discovered.add(parameter_indexes[descendant.id])
            before = len(wrapper_indexes[class_name])
            wrapper_indexes[class_name].update(discovered)
            changed = changed or len(wrapper_indexes[class_name]) != before


def _python_return_source_nodes(
    node: ast.AST,
    assignments: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[int] = frozenset(),
) -> Iterable[ast.AST]:
    if id(node) in seen:
        return
    next_seen = seen | {id(node)}
    for expanded in _python_expand_local_value(node, assignments):
        if expanded is not node:
            yield from _python_return_source_nodes(
                expanded,
                assignments,
                seen=next_seen,
            )
            continue
        if isinstance(expanded, (ast.List, ast.Set, ast.Tuple)):
            for element in expanded.elts:
                yield from _python_return_source_nodes(
                    element,
                    assignments,
                    seen=next_seen,
                )
        elif isinstance(expanded, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            yield from _python_return_source_nodes(
                expanded.elt,
                assignments,
                seen=next_seen,
            )
        elif isinstance(expanded, ast.Dict):
            for value in expanded.values:
                yield from _python_return_source_nodes(
                    value,
                    assignments,
                    seen=next_seen,
                )
        elif isinstance(expanded, ast.DictComp):
            yield from _python_return_source_nodes(
                expanded.value,
                assignments,
                seen=next_seen,
            )
        elif isinstance(expanded, ast.IfExp):
            yield from _python_return_source_nodes(
                expanded.body,
                assignments,
                seen=next_seen,
            )
            yield from _python_return_source_nodes(
                expanded.orelse,
                assignments,
                seen=next_seen,
            )
        elif isinstance(expanded, ast.BoolOp):
            for value in expanded.values:
                yield from _python_return_source_nodes(
                    value,
                    assignments,
                    seen=next_seen,
                )
        elif (
            isinstance(expanded, ast.Call)
            and isinstance(expanded.func, ast.Attribute)
            and expanded.func.attr == "join"
            and expanded.args
        ):
            yield from _python_return_source_nodes(
                expanded.args[0],
                assignments,
                seen=next_seen,
            )
        else:
            yield expanded


def _infer_python_ui_wrappers(
    trees: Iterable[tuple[Path, ast.Module]],
) -> tuple[
    dict[str, set[int]],
    dict[str, set[tuple[str, ...]]],
    set[str],
]:
    trees = tuple(trees)
    definitions: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, tuple[str, ...]]] = []
    signatures: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for _path, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "__init__":
                    continue
                parameters = _python_parameters(node)
                definitions.append((node, parameters))
                signatures[node.name].add(parameters)

    wrapper_indexes: dict[str, set[int]] = defaultdict(set)
    changed = True
    while changed:
        changed = False
        for definition, parameters in definitions:
            parameter_indexes = {
                parameter: index for index, parameter in enumerate(parameters)
            }
            discovered: set[int] = set()
            for node in _walk_python_function_body(definition):
                if not isinstance(node, ast.Call):
                    continue
                sink = _python_call_name(node)
                if sink in _PYTHON_SINKS:
                    candidates = tuple(_python_candidate_nodes(node, sink))
                elif sink in wrapper_indexes:
                    candidates = tuple(
                        _python_wrapper_candidates(
                            node,
                            wrapper_indexes[sink],
                            signatures.get(sink, ()),
                        )
                    )
                else:
                    continue
                for candidate in candidates:
                    for descendant in ast.walk(candidate):
                        if (
                            isinstance(descendant, ast.Name)
                            and descendant.id in parameter_indexes
                        ):
                            discovered.add(parameter_indexes[descendant.id])
            before = len(wrapper_indexes[definition.name])
            wrapper_indexes[definition.name].update(discovered)
            changed = changed or len(wrapper_indexes[definition.name]) != before
    _infer_python_ui_constructors(
        trees,
        wrapper_indexes,
        signatures,
    )
    return (
        wrapper_indexes,
        signatures,
        _python_ui_return_methods(
            definitions,
            wrapper_indexes,
            signatures,
        ),
    )


def _scan_python() -> dict[str, list[dict[str, object]]]:
    origins: dict[str, list[dict[str, object]]] = defaultdict(list)
    trees: list[tuple[Path, ast.Module]] = []
    for source_root in PYTHON_SOURCE_ROOTS:
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            trees.append((path, tree))

    wrapper_indexes, signatures, ui_return_methods = _infer_python_ui_wrappers(trees)
    for path, tree in trees:
        relative = path.relative_to(ROOT).as_posix()
        module_assignments = _python_module_assignments(tree)
        assignments_by_node: dict[int, dict[str, tuple[ast.AST, ...]]] = {}
        for definition in ast.walk(tree):
            if not isinstance(
                definition,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            local_assignments = _python_local_assignments(definition)
            merged_assignments = {
                name: (
                    *module_assignments.get(name, ()),
                    *local_assignments.get(name, ()),
                )
                for name in (
                    set(module_assignments)
                    | set(local_assignments)
                )
            }
            for descendant in _walk_python_function_body(definition):
                assignments_by_node[id(descendant)] = merged_assignments
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            assignments = assignments_by_node.get(id(node), module_assignments)
            sink = _python_call_name(node)
            if sink in _PYTHON_SINKS:
                candidates = tuple(_python_candidate_nodes(node, sink))
            elif sink in wrapper_indexes:
                candidates = tuple(
                    _python_wrapper_candidates(
                        node,
                        wrapper_indexes[sink],
                        signatures.get(sink, ()),
                    )
                )
            else:
                continue
            for candidate in candidates:
                for source_node in _python_return_source_nodes(
                    candidate,
                    assignments,
                ):
                    value = _python_source_value(source_node)
                    for source in _html_segments(value):
                        origins[source].append(
                            {
                                "path": relative,
                                "line": int(getattr(node, "lineno", 0) or 0),
                                "sink": sink,
                            }
                        )
            for filter_node in _python_file_filter_nodes(node, sink):
                for source_node in _python_return_source_nodes(
                    filter_node,
                    assignments,
                ):
                    for source in _file_filter_labels(
                        _python_source_value(source_node)
                    ):
                        origins[source].append(
                            {
                                "path": relative,
                                "line": int(getattr(node, "lineno", 0) or 0),
                                "sink": f"{sink}:filter-label",
                            }
                        )
        for definition in ast.walk(tree):
            if (
                not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef))
                or definition.name not in ui_return_methods
            ):
                continue
            local_assignments = _python_local_assignments(definition)
            assignments = {
                name: (
                    *module_assignments.get(name, ()),
                    *local_assignments.get(name, ()),
                )
                for name in (
                    set(module_assignments)
                    | set(local_assignments)
                )
            }
            for node in _walk_python_function_body(definition):
                if not isinstance(node, ast.Return) or node.value is None:
                    continue
                for candidate in _python_return_source_nodes(
                    node.value,
                    assignments,
                ):
                    value = _python_source_value(candidate)
                    for source in _html_segments(value):
                        origins[source].append(
                            {
                                "path": relative,
                                "line": int(getattr(node, "lineno", 0) or 0),
                                "sink": f"python-return:{definition.name}",
                            }
                        )
    return origins


def _csharp_prefix(text: str, index: int) -> tuple[int, bool, bool] | None:
    for marker, interpolated, verbatim in (
        ('$@"', True, True),
        ('@$"', True, True),
        ('$"', True, False),
        ('@"', False, True),
        ('"', False, False),
    ):
        if text.startswith(marker, index):
            return len(marker), interpolated, verbatim
    return None


def _skip_csharp_character(text: str, index: int) -> int:
    cursor = index + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == "'":
            return cursor + 1
        cursor += 1
    return cursor


def _decode_csharp_escape(text: str, index: int) -> tuple[str, int]:
    if index + 1 >= len(text):
        return "\\", index + 1
    escaped = text[index + 1]
    replacements = {
        "\\": "\\",
        '"': '"',
        "'": "'",
        "0": "\0",
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }
    if escaped in replacements:
        return replacements[escaped], index + 2
    if escaped == "u" and index + 6 <= len(text):
        raw = text[index + 2 : index + 6]
        try:
            return chr(int(raw, 16)), index + 6
        except ValueError:
            pass
    if escaped == "U" and index + 10 <= len(text):
        raw = text[index + 2 : index + 10]
        try:
            return chr(int(raw, 16)), index + 10
        except ValueError:
            pass
    return escaped, index + 2


def _parse_csharp_string(
    text: str,
    start: int,
    *,
    line_offsets: list[int],
) -> tuple[_CSharpString, int, tuple[_CSharpString, ...]] | None:
    prefix = _csharp_prefix(text, start)
    if prefix is None:
        return None
    marker_length, interpolated, verbatim = prefix
    cursor = start + marker_length
    output: list[str] = []
    nested: list[_CSharpString] = []
    placeholder_index = 0
    while cursor < len(text):
        char = text[cursor]
        if char == '"':
            if verbatim and cursor + 1 < len(text) and text[cursor + 1] == '"':
                output.append('"')
                cursor += 2
                continue
            line = bisect.bisect_right(line_offsets, start) + 1
            end = cursor + 1
            return (
                _CSharpString("".join(output), start, end, line),
                end,
                tuple(nested),
            )
        if not verbatim and char == "\\":
            decoded, cursor = _decode_csharp_escape(text, cursor)
            output.append(decoded)
            continue
        if interpolated and char == "{" and not text.startswith("{{", cursor):
            output.append(f"{{value_{placeholder_index}}}")
            placeholder_index += 1
            cursor += 1
            depth = 1
            while cursor < len(text) and depth > 0:
                if text.startswith("//", cursor):
                    newline = text.find("\n", cursor + 2)
                    cursor = len(text) if newline < 0 else newline + 1
                    continue
                if text.startswith("/*", cursor):
                    end_comment = text.find("*/", cursor + 2)
                    cursor = len(text) if end_comment < 0 else end_comment + 2
                    continue
                expression_prefix = _csharp_prefix(text, cursor)
                if expression_prefix is not None:
                    parsed = _parse_csharp_string(
                        text,
                        cursor,
                        line_offsets=line_offsets,
                    )
                    if parsed is not None:
                        inner, cursor, inner_nested = parsed
                        nested.append(inner)
                        nested.extend(inner_nested)
                        continue
                if text[cursor] == "'":
                    cursor = _skip_csharp_character(text, cursor)
                    continue
                if text[cursor] == "{":
                    depth += 1
                elif text[cursor] == "}":
                    depth -= 1
                cursor += 1
            continue
        if interpolated and text.startswith("{{", cursor):
            output.append("{")
            cursor += 2
            continue
        if interpolated and text.startswith("}}", cursor):
            output.append("}")
            cursor += 2
            continue
        output.append(char)
        cursor += 1
    return None


def _iter_csharp_strings(text: str) -> tuple[_CSharpString, ...]:
    line_offsets = [match.start() for match in re.finditer(r"\n", text)]
    strings: list[_CSharpString] = []
    cursor = 0
    while cursor < len(text):
        if text.startswith("//", cursor):
            newline = text.find("\n", cursor + 2)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", cursor):
            end_comment = text.find("*/", cursor + 2)
            cursor = len(text) if end_comment < 0 else end_comment + 2
            continue
        if text[cursor] == "'":
            cursor = _skip_csharp_character(text, cursor)
            continue
        parsed = _parse_csharp_string(text, cursor, line_offsets=line_offsets)
        if parsed is None:
            cursor += 1
            continue
        value, cursor, nested = parsed
        strings.append(value)
        strings.extend(nested)
    return tuple(strings)


def _csharp_sink_regions(text: str) -> tuple[tuple[int, int, str], ...]:
    regions: list[tuple[int, int, str]] = []
    for match in _CSHARP_UI_SINK_RE.finditer(text):
        end_limit = min(len(text), match.start() + _CSHARP_MAX_SINK_REGION_CHARS)
        semicolon = text.find(";", match.end(), end_limit)
        newline_limit = text.find("\n\n", match.end(), end_limit)
        candidates = [
            value
            for value in (semicolon, newline_limit)
            if value >= 0
        ]
        end = min(candidates) + 1 if candidates else end_limit
        sink = re.sub(r"\s+", "", match.group(0))
        regions.append((match.start(), end, sink))
    return tuple(regions)


def _csharp_call_argument_ranges(
    text: str,
    open_paren: int,
    *,
    strings: tuple[_CSharpString, ...],
) -> tuple[tuple[int, int], ...]:
    by_start = {literal.start: literal for literal in strings}
    ranges: list[tuple[int, int]] = []
    argument_start = open_paren + 1
    cursor = argument_start
    paren_depth = 1
    brace_depth = 0
    bracket_depth = 0
    while cursor < len(text):
        literal = by_start.get(cursor)
        if literal is not None:
            cursor = literal.end
            continue
        if text.startswith("//", cursor):
            newline = text.find("\n", cursor + 2)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", cursor):
            end_comment = text.find("*/", cursor + 2)
            cursor = len(text) if end_comment < 0 else end_comment + 2
            continue
        if text[cursor] == "'":
            cursor = _skip_csharp_character(text, cursor)
            continue
        char = text[cursor]
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth == 0:
                ranges.append((argument_start, cursor))
                return tuple(ranges)
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif (
            char == ","
            and paren_depth == 1
            and brace_depth == 0
            and bracket_depth == 0
        ):
            ranges.append((argument_start, cursor))
            argument_start = cursor + 1
        cursor += 1
    return ()


def _csharp_wrapper_regions(
    text: str,
    strings: tuple[_CSharpString, ...],
) -> tuple[tuple[int, int, str], ...]:
    regions: list[tuple[int, int, str]] = []
    for wrapper, indexes in _CSHARP_WRAPPER_ARG_INDEXES.items():
        pattern = re.compile(rf"\b{re.escape(wrapper)}\s*\(")
        for match in pattern.finditer(text):
            open_paren = text.find("(", match.start(), match.end())
            arguments = _csharp_call_argument_ranges(
                text,
                open_paren,
                strings=strings,
            )
            selected = range(len(arguments)) if indexes is None else indexes
            for index in selected:
                if index >= len(arguments):
                    continue
                start, end = arguments[index]
                regions.append((start, end, f"csharp-wrapper:{wrapper}[{index}]"))
    return tuple(regions)


def _csharp_matching_brace(
    text: str,
    open_brace: int,
    *,
    strings: tuple[_CSharpString, ...],
) -> int:
    by_start = {literal.start: literal for literal in strings}
    cursor = open_brace
    depth = 0
    while cursor < len(text):
        literal = by_start.get(cursor)
        if literal is not None:
            cursor = literal.end
            continue
        if text.startswith("//", cursor):
            newline = text.find("\n", cursor + 2)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", cursor):
            end_comment = text.find("*/", cursor + 2)
            cursor = len(text) if end_comment < 0 else end_comment + 2
            continue
        if text[cursor] == "'":
            cursor = _skip_csharp_character(text, cursor)
            continue
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return -1


def _csharp_string_methods(
    text: str,
    *,
    strings: tuple[_CSharpString, ...],
) -> tuple[_CSharpMethod, ...]:
    methods: list[_CSharpMethod] = []
    pattern = re.compile(
        r"\b(?:private|internal|public|protected)\s+"
        r"(?:static\s+)?string\??\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\([^;{}]*\)\s*(?P<body>=>|\{)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        if match.group("body") == "=>":
            end = text.find(";", match.end())
            if end >= 0:
                methods.append(
                    _CSharpMethod(
                        name=match.group("name"),
                        start=match.end(),
                        end=end,
                    )
                )
            continue
        open_brace = text.find("{", match.start(), match.end())
        end = _csharp_matching_brace(
            text,
            open_brace,
            strings=strings,
        )
        if end >= 0:
            methods.append(
                _CSharpMethod(
                    name=match.group("name"),
                    start=open_brace + 1,
                    end=end,
                )
            )
    return tuple(methods)


def _infer_csharp_ui_return_methods(
    documents: dict[
        Path,
        tuple[
            str,
            tuple[_CSharpString, ...],
            tuple[tuple[int, int, str], ...],
        ],
    ],
) -> set[str]:
    methods: dict[str, list[tuple[Path, _CSharpMethod]]] = defaultdict(list)
    sink_fragments: list[str] = []
    for path, (text, strings, sink_regions) in documents.items():
        if path.name != "ExperimentForm.UiLocalization.cs":
            for method in _csharp_string_methods(text, strings=strings):
                methods[method.name].append((path, method))
        sink_fragments.extend(text[start:end] for start, end, _sink in sink_regions)

    selected: set[str] = set()
    for fragment in sink_fragments:
        for method_name in methods:
            if re.search(rf"\b{re.escape(method_name)}\s*\(", fragment):
                selected.add(method_name)

    selected.update(
        method_name
        for method_name in _CSHARP_CROSS_FILE_UI_RETURN_METHODS
        if method_name in methods
    )
    assignment_pattern = re.compile(
        r"\b(?:var|string\??)\s+"
        r"(?P<variable>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"(?P<method>[A-Za-z_][A-Za-z0-9_]*)\s*\("
    )
    for text, _strings, sink_regions in documents.values():
        sink_identifiers = {
            identifier
            for start, end, _sink in sink_regions
            for identifier in re.findall(
                r"\b[A-Za-z_][A-Za-z0-9_]*\b",
                text[start:end],
            )
        }
        for match in assignment_pattern.finditer(text):
            if (
                match.group("variable") in sink_identifiers
                and match.group("method") in methods
            ):
                selected.add(match.group("method"))

    changed = True
    while changed:
        changed = False
        for method_name in tuple(selected):
            for path, method in methods.get(method_name, ()):
                text = documents[path][0]
                body = text[method.start:method.end]
                for candidate in methods:
                    if (
                        candidate not in selected
                        and re.search(rf"\b{re.escape(candidate)}\s*\(", body)
                    ):
                        selected.add(candidate)
                        changed = True
    return selected


def _csharp_ui_return_regions(
    text: str,
    *,
    strings: tuple[_CSharpString, ...],
    selected_methods: set[str],
) -> tuple[tuple[int, int, str], ...]:
    return tuple(
        (
            method.start,
            method.end,
            f"csharp-return:{method.name}",
        )
        for method in _csharp_string_methods(text, strings=strings)
        if method.name in selected_methods
    )


def _scan_csharp() -> dict[str, list[dict[str, object]]]:
    origins: dict[str, list[dict[str, object]]] = defaultdict(list)
    if not CSHARP_SOURCE_ROOT.is_dir():
        return origins
    documents: dict[
        Path,
        tuple[
            str,
            tuple[_CSharpString, ...],
            tuple[tuple[int, int, str], ...],
        ],
    ] = {}
    for path in sorted(CSHARP_SOURCE_ROOT.glob("*.cs")):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        strings = _iter_csharp_strings(text)
        sink_regions = (
            *_csharp_sink_regions(text),
            *_csharp_wrapper_regions(text, strings),
        )
        documents[path] = (text, strings, sink_regions)

    selected_methods = _infer_csharp_ui_return_methods(documents)
    for path, (text, strings, sink_regions) in documents.items():
        relative = path.relative_to(ROOT).as_posix()
        regions = (
            *sink_regions,
            *_csharp_ui_return_regions(
                text,
                strings=strings,
                selected_methods=selected_methods,
            ),
        )
        if not regions:
            continue
        for literal in strings:
            matching = [
                sink
                for start, end, sink in regions
                if start <= literal.start < end
            ]
            if not matching or not _looks_like_translatable_text(literal.value):
                continue
            origins[literal.value].append(
                {
                    "path": relative,
                    "line": literal.line,
                    "sink": f"csharp:{matching[-1]}",
                }
            )
    return origins


def _load_existing_manual_sources() -> set[str]:
    manual: set[str] = set(MANUAL_SOURCE_KEYS)
    if MANIFEST_PATH.is_file():
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for entry in payload.get("entries", ()):
            if isinstance(entry, dict) and entry.get("manual"):
                key = str(entry.get("key", ""))
                if key:
                    manual.add(key)
        return manual
    try:
        sys.path.insert(0, str(ROOT))
        from cdmw.ui.localization_catalogs import SOURCE_STRING_CATALOGUE

        manual.update(str(value) for value in SOURCE_STRING_CATALOGUE)
    except Exception:
        pass
    finally:
        if sys.path and sys.path[0] == str(ROOT):
            sys.path.pop(0)
    return manual


def _load_exclusions() -> tuple[dict[str, str], ...]:
    if not EXCLUSIONS_PATH.is_file():
        return ()
    payload = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("UI localization exclusions must be a JSON array.")
    exclusions: list[dict[str, str]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("Each UI localization exclusion must be an object.")
        path = str(raw.get("path", "")).strip()
        symbol = str(raw.get("symbol", "")).strip()
        source = str(raw.get("source", ""))
        reason = str(raw.get("reason", "")).strip()
        if not path or not symbol or not source or not reason:
            raise ValueError(
                "Every localization exclusion requires path, symbol, source, and reason."
            )
        exclusions.append(
            {"path": path, "symbol": symbol, "source": source, "reason": reason}
        )
    return tuple(exclusions)


def build_manifest() -> dict[str, object]:
    origins = _scan_python()
    for source, rows in _scan_csharp().items():
        origins[source].extend(rows)
    exclusions = _load_exclusions()
    for exclusion in exclusions:
        source = exclusion["source"]
        path = exclusion["path"]
        if source == "*":
            for candidate in tuple(origins):
                origins[candidate] = [
                    row
                    for row in origins[candidate]
                    if str(row.get("path", "")) != path
                ]
                if not origins[candidate]:
                    origins.pop(candidate, None)
            continue
        origins[source] = [
            row for row in origins.get(source, ()) if str(row.get("path", "")) != path
        ]
        if not origins[source]:
            origins.pop(source, None)
    manual_sources = _load_existing_manual_sources()
    keys = sorted(set(origins) | manual_sources)
    entries: list[dict[str, object]] = []
    for key in keys:
        rows = sorted(
            origins.get(key, ()),
            key=lambda row: (
                str(row.get("path", "")),
                int(row.get("line", 0) or 0),
                str(row.get("sink", "")),
            ),
        )
        entry: dict[str, object] = {"key": key, "origins": rows}
        if key in manual_sources and not rows:
            entry["manual"] = True
        entries.append(entry)
    return {
        "schema": "cdmw_ui_localization_source_manifest_v1",
        "entries": entries,
        "exclusions": list(exclusions),
    }


def _english_catalog(manifest: dict[str, object]) -> dict[str, object]:
    entries = manifest.get("entries", ())
    keys = [
        str(entry.get("key", ""))
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("key", ""))
    ]
    return {
        "schema_version": 2,
        "language_code": "en",
        "language_name": "English",
        "translations": {
            key: (
                {"one": "{count} file", "other": "{count} files"}
                if key == "{count} files"
                else key
            )
            for key in keys
        },
    }


def _dotnet_keys(manifest: dict[str, object]) -> tuple[str, ...]:
    keys: list[str] = []
    for entry in manifest.get("entries", ()):
        if not isinstance(entry, dict):
            continue
        if any(
            str(origin.get("path", "")).startswith(
                "tools/dotnet_mesh_editor_experiment/"
            )
            for origin in entry.get("origins", ())
            if isinstance(origin, dict)
        ):
            keys.append(str(entry.get("key", "")))
    return tuple(sorted(filter(None, keys)))


def _dotnet_keys_block(keys: Iterable[str]) -> str:
    lines = [DOTNET_KEYS_BEGIN]
    for key in keys:
        lines.append(f"        {json.dumps(key, ensure_ascii=False)},")
    lines.append(DOTNET_KEYS_END)
    return "\n".join(lines)


def _expected_dotnet_source(manifest: dict[str, object]) -> str:
    source = DOTNET_LOCALIZATION_PATH.read_text(encoding="utf-8-sig")
    start = source.find(DOTNET_KEYS_BEGIN)
    end = source.find(DOTNET_KEYS_END)
    if start < 0 or end < start:
        raise ValueError(
            f"{DOTNET_LOCALIZATION_PATH.relative_to(ROOT)} is missing generated-key markers."
        )
    end += len(DOTNET_KEYS_END)
    return source[:start] + _dotnet_keys_block(_dotnet_keys(manifest)) + source[end:]


def _serialized(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write the manifest and English catalog.")
    parser.add_argument("--check", action="store_true", help="Fail if packaged files are stale.")
    args = parser.parse_args()
    if args.write == args.check:
        parser.error("Choose exactly one of --write or --check.")
    manifest = build_manifest()
    english = _english_catalog(manifest)
    expected = {
        MANIFEST_PATH: _serialized(manifest),
        ENGLISH_CATALOG_PATH: _serialized(english),
        DOTNET_LOCALIZATION_PATH: _expected_dotnet_source(manifest),
    }
    if args.write:
        RESOURCE_ROOT.mkdir(parents=True, exist_ok=True)
        for path, text in expected.items():
            path.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {len(english['translations']):,} UI localization source keys.")
        return 0
    stale = []
    for path, text in expected.items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        if actual != text:
            stale.append(path.relative_to(ROOT))
    if stale:
        print("Stale UI localization files: " + ", ".join(str(path) for path in stale))
        return 1
    print(f"UI localization manifest is current: {len(english['translations']):,} keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
