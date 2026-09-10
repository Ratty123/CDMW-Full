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
BUILTIN_TRANSLATION_CODES = (
    "de",
    "es-419",
    "es-ES",
    "fr",
    "it",
    "ja",
    "ko",
    "pl",
    "pt-BR",
    "ru",
    "tr",
    "zh-Hans",
    "zh-Hant",
)
EXCLUSIONS_PATH = ROOT / "scripts" / "ui_localization_exclusions.json"

PYTHON_SOURCE_ROOTS = (
    ROOT / "cdmw" / "app",
    ROOT / "cdmw" / "services",
    ROOT / "cdmw" / "ui",
    ROOT / "cdmw" / "workers",
    ROOT / "tools" / "placement_studio",
    ROOT / "tools" / "format_explorer",
    ROOT / "tools" / "translation_studio",
)
MANUAL_SOURCE_KEYS = frozenset(
    {
        # Preview Core selects recovery guidance by the native filesystem error.
        "A required file is missing. Refresh the archive catalogue and select the model again.",
        "Access was denied. Check permissions for the workspace and source files.",
        "A file path is too long. Use a shorter app or workspace location.",
        "A file path is invalid. Check the workspace and source locations.",
        "Select the model again to retry.",
        # Archive action menus remove the file-dialog ellipsis from this label.
        "Replace Mesh from File",
        # Shared preview combo labels arrive through imported option tables.
        # Keep their Qt translations independent of the help's wording.
        "Solid (Textured)", "Faces (No Textures)", "Faces + Wire", "Wire",
        "Vertices", "Wire + Vertices", "X-Ray", "Solid", "Faces", "Face+W",
        "Verts", "Wire+V",
        # Lazy shell registration supplies this title through a factory call.
        "Texture Recolor",
        # New Item reports use deferred ModelFiles fields and a typed rig error.
        "The imported skin weights reference bones outside the target palette.",
        "Armour weight donor: {value_0}",
        "Armour weights were transferred from the character body. Check fit and deformation; cloth simulation is not rebuilt.",
        # Pure overlay composition errors reach the installed-overlay dialog.
        "Overlay conflict in {value_0}; both installs change the same record.",
        "Unsupported table directory layout.",
        "Incomplete table row directory.",
        "Duplicate primary keys in an overlay table.",
        "Table layout changed in {value_0}.",
        "Unsupported icon registry in {value_0}.",
        "Both table files are required to compose {value_0}.",
        "Overlay conflict in {value_0}; overlapping file edits cannot be separated safely.",
        "Shop price: {value_0} owned perk copies with zero price contribution; bonuses retained",
        "The {value_0} table has no localization for perk {value_1}: {value_2}",
        # Placement's model headers and prepared checks are indirect data sinks.
        "Use", "Target file", "Replacement", "Action", "Rig", "Variant", "Checks", "Shared impact",
        "Passed", "Warning", "Unverified", "Blocked", "Scope", "Payload", "Timing", "File set",
        "Contact", "Transitions", "In game", "Relationship coverage", "Full/LOD companion",
        "Part-shrink settings", "Retarget alignment", "Movement compatibility", "Bone mapping",
        "Motion differences", "Animation scale metadata", "Destination fit", "Character proportions",
        "Clearance", "Attachment binding", "Attachment events", "Attachment track", "Installed placement source",
        "Placement only", "Draw and stow only", "Draw, stow, and stowed locomotion",
        "Full-body family replacement (advanced)",
        # Prepared evidence and preview notes are rendered through deferred data models.
        "Chart handoffs: Passed; initial state selected manually",
        "Chart handoffs: Unverified — {value_0}",
        "Chart handoffs: Unverified for this preview; using the initial state",
        "Automatic parameter calculation: Unverified; manual inputs precede the stored parameter scale",
        "Stored character scale: {value_0}; automatic actor inputs Unverified",
        "Previous-motion weights: Unverified; inspecting manually initialized weights",
        "Unsupported initial weight mode: {value_0}",
        "Degenerate stored triangles: excluded from interpolation",
        "Runtime action selection, conditions and inherited attachment state are not simulated",
        "Attachment deformation: Unverified — {value_0}",
        "{value_0} (0x{value_1}) is an optional leaf absent from this mesh; no target bone descends from it. Witness: {value_2}; SHA-256 {value_3}",
        "Weighted slots {value_0} exceed the validated {value_1}-bone palette",
        "An attachment event lies beyond this clip duration",
        "An event socket frame is unavailable in this preview state",
        "Attachment events on a chart blendspace are not simulated",
        "Chart actions disagree on this part's attachment timeline",
        "No decoded action timeline references this clip",
        "No attachment events address this part",
        "This action also changes equipment or docking through unsupported events",
        "Event conditions are not simulated",
        "Event execution flags are unsupported",
        "Event interval is unsupported",
        "Socket blend interpolation is not simulated",
        "Event uses an unsupported execution branch",
        "Equipment-slot lookup is unresolved",
        "All-parts mode is unsupported",
        "Explicit socket pair is incomplete",
        "Global chart events are not simulated",
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
        "No Matching Topics",
        "No to All",
        "No placement chain",
        (
            "No topic contains every search word. Try fewer words or search for "
            "a tool, action, file format, or setting."
        ),
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
        "Texture Research",
        "Updating app colors and preview panes...",
        "Yes",
        "Yes to All",
        "Zlib",
        "{value_0}; unresolved {value_1}",
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
        "{count} topics",
        # Shared-memory descriptor validation is owned by the pure mesh domain.
        # Its error is presented by the UI, but domain files are not scanned.
        "Invalid resident interaction transaction descriptor.",
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
RETIRED_MANUAL_SOURCE_KEYS = frozenset({"Recolor Variants"})

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
    "OverlayConflict",
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
    "_log_progress",
    "_resolve_package_output_path",
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
    # New Item Studio's tinted vocabulary (cdmw/ui/new_item/ui_kit.py): the text is the first argument
    "DetailsToggle",
    "NoteLabel",
    "intro_label",
    "note",
    "set_note",
    "tinted",
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
    "ConfigureCombo": (1, 2, 3, 4, 5, 6),
    "ConfigureMorphStatusLabel": (1,),
    "CreateDockHeader": (1,),
    "CreateMorphCompactCard": (0, 1),
    "GizmoButton": (0,),
    "LabeledControl": (0,),
    "MorphStepLabel": (0,),
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
    r"\bText\s*=(?!=)|\.Text\s*=(?!=)|SetToolTip\s*\(|MessageBox\.Show\s*\(|"
    r"StatusRequested\?\.Invoke\s*\(|"
    r"Set(?:Status|Hint)\s*\(|SetAccessible|"
    r"Accessible(?:Name|Description)\s*=(?!=)|ToolTipText\s*=(?!=)|"
    r"new\s+(?:Button|Label|CheckBox|RadioButton|GroupBox|ToolStripMenuItem|"
    r"ToolStripButton|TabPage|ComboBoxItem)\s*[\(\{]|"
    r"\.Items\.Add\s*\(|\.Items\.AddRange\s*\(|\.TabPages\.Add\s*\("
    r")"
)
_CSHARP_MAX_SINK_REGION_CHARS = 8_000



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
        # Runtime rich-text translation keeps punctuation after an inline tag.
        # A leading ". " is sentence text here, not the path-like value that
        # the general source filter deliberately excludes.
        sentence_after_tag = (
            normalized[1:].lstrip()
            if normalized.startswith(". ")
            else normalized
        )
        if _looks_like_translatable_text(
            normalized
        ) or _looks_like_translatable_text(sentence_after_tag):
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
    visited: set[int] | None = None,
) -> Iterable[ast.AST]:
    if visited is None:
        visited = set()
    if id(node) in seen or id(node) in visited:
        return
    visited.add(id(node))
    reference_name = _python_reference_name(node)
    next_seen = seen | {id(node)}
    if reference_name:
        assigned_values = assignments.get(reference_name, ())
        if assigned_values:
            for assigned_value in assigned_values:
                yield from _python_return_source_nodes(
                    assigned_value,
                    assignments,
                    seen=next_seen,
                    visited=visited,
                )
            return
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        for element in node.elts:
            yield from _python_return_source_nodes(
                element,
                assignments,
                seen=next_seen,
                visited=visited,
            )
    elif isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        yield from _python_return_source_nodes(
            node.elt,
            assignments,
            seen=next_seen,
            visited=visited,
        )
    elif isinstance(node, ast.Dict):
        for value in node.values:
            yield from _python_return_source_nodes(
                value,
                assignments,
                seen=next_seen,
                visited=visited,
            )
    elif isinstance(node, ast.DictComp):
        yield from _python_return_source_nodes(
            node.value,
            assignments,
            seen=next_seen,
            visited=visited,
        )
    elif isinstance(node, ast.IfExp):
        yield from _python_return_source_nodes(
            node.body,
            assignments,
            seen=next_seen,
            visited=visited,
        )
        yield from _python_return_source_nodes(
            node.orelse,
            assignments,
            seen=next_seen,
            visited=visited,
        )
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _python_return_source_nodes(
                value,
                assignments,
                seen=next_seen,
                visited=visited,
            )
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and node.args
    ):
        yield from _python_return_source_nodes(
            node.args[0],
            assignments,
            seen=next_seen,
            visited=visited,
        )
    else:
        yield node


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




























def _load_existing_manual_sources() -> set[str]:
    manual: set[str] = set(MANUAL_SOURCE_KEYS)
    if MANIFEST_PATH.is_file():
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for entry in payload.get("entries", ()):
            if isinstance(entry, dict) and entry.get("manual"):
                key = str(entry.get("key", ""))
                if key and key not in RETIRED_MANUAL_SOURCE_KEYS:
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
                else {"one": "{count} topic", "other": "{count} topics"}
                if key == "{count} topics"
                else key
            )
            for key in keys
        },
    }








def _serialized(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _synchronized_builtin_catalogs(
    english: dict[str, object],
) -> dict[Path, str]:
    """Retain reviewed translations while pruning retired production keys."""
    english_entries = english.get("translations")
    if not isinstance(english_entries, dict):
        raise ValueError("English catalog has no translations object.")
    synchronized: dict[Path, str] = {}
    for code in BUILTIN_TRANSLATION_CODES:
        path = RESOURCE_ROOT / f"{code}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path.relative_to(ROOT)} is not a JSON object.")
        translations = payload.get("translations")
        if not isinstance(translations, dict):
            raise ValueError(f"{path.relative_to(ROOT)} has no translations object.")
        payload["translations"] = {
            key: translations.get(key, fallback)
            for key, fallback in english_entries.items()
        }
        synchronized[path] = _serialized(payload)
    return synchronized


def _manifest_freshness_view(payload: object) -> object:
    """Return the manifest contract with informational source lines removed."""
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return normalized
    normalized_entries: list[object] = []
    for entry in entries:
        if not isinstance(entry, dict):
            normalized_entries.append(entry)
            continue
        normalized_entry = dict(entry)
        origins = entry.get("origins")
        if isinstance(origins, list):
            normalized_origins = [
                (
                    {key: value for key, value in origin.items() if key != "line"}
                    if isinstance(origin, dict)
                    else origin
                )
                for origin in origins
            ]
            normalized_entry["origins"] = sorted(
                normalized_origins,
                key=lambda origin: json.dumps(
                    origin,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        normalized_entries.append(normalized_entry)
    normalized["entries"] = normalized_entries
    return normalized


def _content_is_current(path: Path, actual: str, expected: str) -> bool:
    if path != MANIFEST_PATH:
        return actual == expected
    try:
        actual_payload = json.loads(actual)
        expected_payload = json.loads(expected)
    except (TypeError, ValueError):
        return False
    return _manifest_freshness_view(actual_payload) == _manifest_freshness_view(
        expected_payload
    )


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
    }
    expected.update(_synchronized_builtin_catalogs(english))
    if args.write:
        RESOURCE_ROOT.mkdir(parents=True, exist_ok=True)
        for path, text in expected.items():
            path.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {len(english['translations']):,} UI localization source keys.")
        return 0
    stale = []
    for path, text in expected.items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not _content_is_current(path, actual, text):
            stale.append(path.relative_to(ROOT))
    if stale:
        print("Stale UI localization files: " + ", ".join(str(path) for path in stale))
        return 1
    print(f"UI localization manifest is current: {len(english['translations']):,} keys.")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
