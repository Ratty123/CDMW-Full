"""Reporting choices and examples for the tools exposed by the CDMW shell."""

from __future__ import annotations

from dataclasses import dataclass


INTERFACE_ACTION = "Window / layout / controls"
OTHER_ACTION = "Other / not sure"
MOD_STATES = ("No mods installed", "Mods installed", "Not sure")
MOD_MANAGERS = ("CDMW overlays", "CDUMM", "Definitive Mod Manager", "JMM", "Crimson Sharp / Crimson Browser",
                "Field-JSON", "Manual installation", "Another manager", "Not sure")
INSTALL_METHODS = ("Not installed yet", "Manager folder / ZIP", "CDMW overlay", "Manual loose files",
                   "Direct archive edits", "Another method", "Not sure")
GAME_INVOLVEMENT = ("Yes", "No", "Not sure")


@dataclass(frozen=True)
class ReportTool:
    key: str
    label: str
    actions: tuple[str, ...]
    sources: tuple[str, ...]
    item_label: str
    item_hint: str
    steps_hint: str
    help: str
    aliases: tuple[str, ...] = ()
    game_related: bool = True
    mod_output: bool = False


MODEL_SOURCES = ("Game model (PAC / PAM / PAMLOD)", "GLB / glTF", "OBJ", "FBX", "DAE",
                 "CDMW project / editable package", "Other / not sure")
TEXTURE_SOURCES = ("DDS from game archives", "Local DDS", "PNG / JPEG / WebP", "Mod folder / ZIP",
                   "Texture project / session", "Other / not sure")

REPORT_TOOLS = (
    ReportTool("archive_browser", "Browse Archives",
        ("Scan / open archives", "Search / filter files", "Preview a file", "Extract files",
         "Export a mod package", "Edit / replace archive content", "HKX / animation tools", "Material / XML tools"),
        ("PAMT / PAZ archive", "PAC / PAM / PAMLOD model", "DDS texture", "HKX / PAB", "Material / XML / table", OTHER_ACTION),
        "Archive file / asset", "e.g. character/armor/item.pac",
        "1. Open the archive.\n2. Select the file.\n3. Choose the action that failed.",
        "Include the archive-relative path and the action/menu used. For preview issues, name the view and missing content.",
        aliases=("Archive Browser",), mod_output=True),
    ReportTool("new_item_studio", "Create New Item",
        ("Choose a template / item", "Import a model", "Model & Placement", "Appearance / shader controls",
         "Identity / stats", "Perks / Effects", "Item icons", "Build / export a mod", "Save / reopen a draft"),
        ("Existing game item", "Imported model", "Saved CDMW draft", OTHER_ACTION),
        "Template / item / model", "Item name, template or model filename",
        "1. Choose the template/model.\n2. Change the named setting.\n3. Preview or build.",
        "Include the character/template, model and affected setting. For effects, name the effect and attachment.",
        aliases=("New Item Studio", "New Item"), mod_output=True),
    ReportTool("model_library", "Model Library",
        ("Search / browse models", "Download / import a model", "Preview a model", "Materials / textures",
         "Open in another tool", "Catalogue / mirror / cache"), MODEL_SOURCES,
        "Model / catalogue entry", "Model name or filename; catalogue entry if relevant",
        "1. Find or import the model.\n2. Open its preview.\n3. Choose the affected action.",
        "Name the model, source format and catalogue/mirror if used. Include which textures or parts are missing."),
    ReportTool("item_icons", "Item Icons",
        ("Browse / import icons", "Create / generate an icon", "Preview / background", "Match an item",
         "Export / patch an icon", "Save / edit icon metadata"),
        ("Game icon / DDS", "Local image", "Generated icon", "Mod folder / ZIP", OTHER_ACTION),
        "Item / icon", "Item name, icon filename or library entry",
        "1. Choose the item/icon.\n2. Set the background or generation options.\n3. Preview or export.",
        "Name the item/icon and source. For generated icons, include the selected model and background.", mod_output=True),
    ReportTool("mesh_editor", "Mesh Editor",
        ("Open / load a model", "Preview / camera / display", "Parts / materials / textures", "Shader experiments",
         "Selection / transforms", "Sculpt / topology / normals", "UV editing", "Rig / skin weights",
         "Morph & Refit", "Cloth", "Vertex Parameters", "Hair Tools / Appearance",
         "Import Replacement / editable exchange", "Validation", "Build / export a mod", "Undo / redo / save session"),
        MODEL_SOURCES, "Model / part", "Model filename or archive path; affected part if known",
        "1. Open the model.\n2. Select the part and control.\n3. Apply the change, preview or export.",
        "Include the model and part, exact control/value, and whether the problem is in preview, validation, export or the game.",
        mod_output=True),
    ReportTool("placement_studio", "Placement & Animations",
        ("Open an item / character", "Placement / sockets", "Animation / pose preview", "Skeleton / attachments",
         "Save / reopen a project", "Export placement / animations"),
        ("Game item / model", "HKX animation", "Saved placement project", OTHER_ACTION),
        "Item / character / animation", "Item, character and animation/clip name",
        "1. Open the item/character.\n2. Select the socket or animation.\n3. Move, preview or export.",
        "Name the character/item, socket or animation clip, and the placement/preview setting.",
        aliases=("Placement Studio",), mod_output=True),
    ReportTool("textures", "Textures",
        ("Add files / folder / mod", "Edit / paint / layers", "Recolor", "Upscale / AI backend",
         "Replace / match originals", "Review & Export", "Workflow profiles / rules", "Save / reopen a project"),
        TEXTURE_SOURCES, "Texture / mod", "Texture filename or archive-relative DDS path",
        "1. Add the texture/mod.\n2. Choose Edit, Recolor, Upscale or Replace.\n3. Apply or export.",
        "Name the texture, mode and setting. For upscale, include the backend/model; for Replace, include the original and replacement.",
        aliases=("Texture Workflow", "Texture Editor", "Recolor", "Upscale"), mod_output=True),
    ReportTool("mod_management", "Mod Management",
        ("Installed overlays / enable / disable", "Preview an installed item", "Merge mod folders",
         "Compare updates / export", "Move items into an overlay", "Recovery / restore"),
        ("Installed CDMW overlay", "Mod folder / ZIP", "Recovery set", OTHER_ACTION),
        "Mod / overlay / recovery set", "Mod name and version, or recovery-set name",
        "1. Select the mod/overlay.\n2. Choose the management action.\n3. Confirm or preview.",
        "Name the affected mod/overlay and action. For merges or updates, name both inputs and the selected conflict option.", mod_output=True),
    ReportTool("mod_package_retrofit", "Repackage Mods",
        ("Scan / add packages", "Choose manager / structure", "Repair paths", "Repackage / export"),
        ("Mod folder", "ZIP package", OTHER_ACTION), "Mod package", "Package name and target manager",
        "1. Add the package.\n2. Choose manager, structure and repair options.\n3. Repackage.",
        "Include the package, selected manager/structure, repair options and the output that failed.",
        aliases=("Retrofit/Repackage Mods", "Mod Package Retrofit"), mod_output=True),
    ReportTool("format_explorer", "Inspect File Formats",
        ("Open / decode a file", "Browse structure / fields", "Compare files", "Export decoded content"),
        ("Game archive file", "Extracted / local file", OTHER_ACTION), "File / format", "Filename, format and affected field",
        "1. Open the file.\n2. Choose the decoder/view.\n3. Inspect or export the affected field.",
        "Name the format/file, decoder/view and the field or section that looks incorrect.", aliases=("Format Explorer",)),
    ReportTool("translation_studio", "Edit Translations",
        ("Open / load translations", "Search / edit text", "AI translation", "Validate translations", "Export / save"),
        ("Game translation file", "Exported translation file", OTHER_ACTION), "Translation / text entry",
        "Filename, language and text ID / entry",
        "1. Open the translation file.\n2. Select language and entry.\n3. Edit, translate or export.",
        "Include the language pair, entry/ID and action. For AI translation, name the provider/model; never include an API key.",
        aliases=("Translation Studio",), mod_output=True),
    ReportTool("research", "Asset Research",
        ("Search / find an asset", "Inspect dependencies / references", "Compare / analyse", "Export results"),
        (), "Query / asset", "Search term or archive-relative asset path",
        "1. Enter the query/asset.\n2. Choose the search or analysis.\n3. Open or export the result.",
        "Include the query/asset, selected analysis and the result or reference that was missing.", aliases=("Research",)),
    ReportTool("text_search", "Search File Text",
        ("Choose files / scope", "Search text", "Filter / open results", "Export results"),
        (), "Search term / file", "Query and file/scope where the match was expected",
        "1. Choose the files/scope.\n2. Enter the search term and options.\n3. Run the search.",
        "Include the exact search term, file/scope, filters and a sample match you expected.", aliases=("Text Search",)),
    ReportTool("settings", "Settings / profiles",
        ("Game folder / archive setup", "Display / theme / language", "External tool / backend settings",
         "Save / restore settings", "Import / export a profile"), (), "Setting / profile", "Setting or profile name",
        "1. Open the settings page.\n2. Change the named option.\n3. Save, reopen or restart.",
        "Name the settings page and option. Include the old/new values; never include keys, passwords or private paths.",
        aliases=("Settings", "Profile"), game_related=False),
    ReportTool("application", "CDMW startup / main window",
        ("Start / close CDMW", "Open / switch a tool", "Detach / reattach a window", "Display scaling / layout",
         "Help / diagnostics / problem reporting"), (), "", "",
        "1. Start CDMW.\n2. Open the tool/menu.\n3. Describe the last action before the problem.",
        "Include the launch method and last action. For layout issues, include display scale and whether a monitor move was involved.",
        game_related=False),
    ReportTool("other", "Other / not sure", (OTHER_ACTION,), (), "Item / file", "Item or file, if one is involved",
        "1. Open the feature.\n2. Choose the action.\n3. Describe the result.",
        "Name the feature and the buttons you used. Select a named tool above when possible.", game_related=False),
)

ACTION_HELP = {
    "Parts / materials / textures": "Name the part, material/texture slot, display mode and missing or incorrect texture.",
    "Shader experiments": "Name the part, source shader, experiment and changed values. Compare preview and exported/in-game results.",
    "Cloth": "Name the part, cloth profile/control and value. Say whether the issue is in the preview or exported result.",
    "Vertex Parameters": "Name the part, channel and edited value. Include whether Apply was pressed and how the result was checked.",
    "Hair Tools / Appearance": "Name the scalp/part, tool or preset, appearance control and the last completed action.",
    "Rig / skin weights": "Name the bone/part, weighting action and the pose that exposes the problem.",
    "UV editing": "Name the part, UV set and operation. Include the texture/view used to check the result.",
    "Morph & Refit": "Name the part, target/character and parameter values used for the refit.",
    "Import Replacement / editable exchange": "Name the input format and source model. Say whether the matching CDMW companion was present and paste validation errors.",
    "Recolor": "Name the texture/mod, selected recolor method and colour/alpha options.",
    "Upscale / AI backend": "Name the backend/model, scale and settings. Include the last progress/error; never paste credentials.",
    "Replace / match originals": "Name both the replacement and original DDS, matching mode and unresolved/incorrect match.",
    "Perks / Effects": "Name the perk/effect, target item, socket/attachment and setting. Describe preview and exported/game results separately.",
    "Recovery / restore": "Name the recovery set and chosen action. Include the error and what was restored; do not repeat archive writes just for this report.",
    "Game folder / archive setup": "Name the folder type, scan/setup action and error. Use game-relative names instead of your full personal path.",
    INTERFACE_ACTION: "Name the affected panel/control, window size or display scale, and how to trigger the layout problem.",
}


def report_tool(key_or_label: str) -> ReportTool:
    value = str(key_or_label).strip().casefold()
    return next((tool for tool in REPORT_TOOLS if value in
                 {tool.key.casefold(), tool.label.casefold(), *(alias.casefold() for alias in tool.aliases)}), REPORT_TOOLS[-1])


def tool_actions(tool: ReportTool) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*tool.actions, INTERFACE_ACTION, OTHER_ACTION)))


def encode_tool(tool: ReportTool, action: str, other: str = "") -> str:
    label = other.strip() if tool.key == "other" else tool.label
    return f"{label} — {action}" if action else label


def decode_tool(value: str) -> tuple[ReportTool, str, str]:
    label, _separator, action = value.partition(" — ")
    tool = report_tool(label)
    return tool, action if action in tool_actions(tool) else "", label if tool.key == "other" else ""


def encode_item(source: str, item: str) -> str:
    return f"Source: {source}\nItem: {item}" if source else item


def decode_item(value: str) -> tuple[str, str]:
    if value.startswith("Source: ") and "\nItem: " in value:
        source, item = value.removeprefix("Source: ").split("\nItem: ", 1)
        return source, item
    return "", value


def encode_mod_setup(state: str, manager: str, method: str, notes: str) -> str:
    if state == "No mods installed" and not any((manager, method, notes.strip())):
        return "None"
    return (f"Mods: {state}\nManager: {manager or 'Not sure'}\nInstallation: {method or 'Not sure'}"
            f"\nRelevant mods: {notes.strip() or 'Not sure'}")


def decode_mod_setup(value: str) -> tuple[str, str, str, str]:
    if value == "None":
        return "No mods installed", "", "", ""
    if value.startswith("Mods: ") and "\nRelevant mods: " in value:
        fields, notes = value.split("\nRelevant mods: ", 1)
        parts = dict(line.split(": ", 1) for line in fields.splitlines() if ": " in line)
        if parts.get("Mods") in MOD_STATES:
            return parts["Mods"], parts.get("Manager", ""), parts.get("Installation", ""), notes
    return "Not sure", "Not sure", "Not sure", value
