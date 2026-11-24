"""The arguments each Mesh Editor panel command takes, as its Python handler reads them.

The panel tools (``mesh.weights``, ``mesh.morph``, ``mesh.refit``, ``mesh.cloth``,
``mesh.layers``, ``mesh.part_options``) and the ``params`` of ``mesh.topology`` and
``mesh.mesh_action`` send one command per call with an ``arguments`` object. The schema
checker takes no ``oneOf``, so each tool lists the union of its commands' fields, typed,
and the handler checks the call against its command's own shape (:func:`check`) before
anything is sent: unknown fields and missing required ones are refused with the command's
own field list. The shapes come from the handlers (``mesh_rust_authoring._execute_shadow_command``,
``_run_morph_command`` and the services they call); keys the host adds itself
(``selection`` and ``_private`` ones) are not listed.
"""

from __future__ import annotations

from collections.abc import Mapping

from cdmw.mcp.errors import INVALID_ARGUMENTS, ToolError

STRING = {"type": "string", "maxLength": 256}
NAME = {"type": "string", "minLength": 1, "maxLength": 128}
PATH = {"type": "string", "minLength": 3, "maxLength": 1024}
BOOL = {"type": "boolean"}
NUMBER = {"type": "number"}
INT = {"type": "integer", "minimum": 0}
PARTS = {"type": "array", "maxItems": 4096, "items": {"type": "integer", "minimum": 0},
         "description": "Part numbers, as mesh_state lists them."}
VEC3 = {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}
ISLANDS = {"type": "array", "maxItems": 4096, "description": "Whole islands: each {submesh_index, face_indices}.",
           "items": {"type": "object", "additionalProperties": False, "required": ["submesh_index", "face_indices"],
                     "properties": {"submesh_index": INT,
                                    "face_indices": {"type": "array", "maxItems": 200000, "items": INT}}}}


def _d(schema: Mapping[str, object], text: str) -> dict[str, object]:
    return {**schema, "description": text}


def shape(properties: Mapping[str, Mapping[str, object]] | None = None, required=(), text: str = "") -> dict:
    """One command's arguments."""

    return {"properties": dict(properties or {}), "required": list(required), "text": text}


NONE = shape(text="no arguments")

# ----- Morph & Refit: morphs --------------------------------------------------------------
_GARMENTS = _d(PARTS, "Garment parts (bound to the driver); empty: the selected parts.")
_PHASE_END = {"type": "string", "enum": ["end"], "default": "end"}
_PERCENT_RANGE = {"min_percent": NUMBER, "max_percent": NUMBER, "default_percent": NUMBER}
_DEFINITION = {"type": "object", "additionalProperties": False,
               "required": ["profile_id", "profile_name", "definition_id", "label"],
               "description": "A procedural slider, on the selected vertices (unless preserve_selection).",
               "properties": {
                   "profile_id": _d(STRING, "The profile; \"\" makes a new one."),
                   "profile_name": STRING, "definition_id": NAME, "label": NAME,
                   "category": STRING,
                   "rule": {"type": "string", "enum": ["volume", "scale", "move", "flatten", "taper", "twist",
                                                      "radius"]},
                   "axis": {"type": "string", "enum": ["x", "y", "z"]},
                   "amount": NUMBER, "feather": INT,
                   "falloff": {"type": "string", "enum": ["constant", "linear", "smooth"]},
                   "mirror_mode": {"type": "string", "enum": ["off", "x", "y", "z"]},
                   **_PERCENT_RANGE,
                   "local_basis": {"type": "array", "minItems": 3, "maxItems": 3, "items": VEC3,
                                   "description": "Three orthogonal axes."},
                   "preserve_selection": _d(BOOL, "Keep the slider's vertices (with source_definition_id)."),
                   "source_definition_id": _d(STRING, "The slider this one replaces.")}}
_AUTHORED = {"type": "object", "additionalProperties": False, "required": ["definition_id", "label"],
             "description": "The sculpted shape since capture_baseline, saved as a slider.",
             "properties": {"profile_id": STRING, "profile_name": STRING, "definition_id": NAME, "label": NAME,
                            "category": STRING, **_PERCENT_RANGE}}

MORPH: dict[str, dict] = {
    "activate": shape({"profile_id": NAME}, ["profile_id"], "switch to a saved profile"),
    "apply_preset": shape({"preset_id": NAME}, ["preset_id"], "apply a preset of the active profile"),
    "apply_setup": shape({"recipe_id": NAME, "garment_submesh_indices": _GARMENTS}, ["recipe_id"],
                         "apply a saved fitting setup (setup-<32 hex>)"),
    "bake": shape(text="bake the current morph into the mesh"),
    "begin_correction": shape({"definition_id": NAME, "garment_submesh_indices": _GARMENTS}, ["definition_id"],
                              "start an outfit correction for a slider"),
    "cancel_baseline": NONE,
    "cancel_correction": NONE,
    "capture_authored": shape({"definition": _AUTHORED}, ["definition"],
                              "save the sculpted shape as a slider (after capture_baseline, all sliders at 0)"),
    "capture_baseline": shape({"submesh_indices": _d(PARTS, "Body parts to sculpt; empty: the selected parts.")},
                              (), "capture the neutral base before sculpting"),
    "clear_driver_region": shape({"garment_submesh_indices": _GARMENTS}, ["garment_submesh_indices"]),
    "clear_influence": shape({"garment_submesh_indices": _GARMENTS}),
    "create": shape({"definition": _DEFINITION}, ["definition"], "add or update a procedural slider"),
    "delete_definition": shape({"definition_id": NAME}, ["definition_id"]),
    "delete_preset": shape({"preset_id": NAME}, ["preset_id"]),
    "delete_profile": shape({"profile_id": NAME}, ["profile_id"]),
    "generate_body_controls": NONE,
    "import_preset": shape({"path": _d(PATH, "An existing portable preset .json."), "name": STRING}, ["path"]),
    "import_recipe": shape({"path": _d(PATH, "An existing fitting recipe .json."), "name": STRING,
                            "garment_submesh_indices": _GARMENTS}, ["path"]),
    "reset": NONE,
    "reset_correction": shape({"definition_id": NAME, "garment_submesh_indices": _GARMENTS}, ["definition_id"]),
    "reset_macros": NONE,
    "save_correction": NONE,
    "save_preset": shape({"preset_id": NAME, "name": STRING}, ["preset_id"]),
    "save_profile": NONE,
    "save_setup": shape({"name": NAME}, ["name"], "save a reusable fitting setup"),
    "set_corrections_enabled": shape({"enabled": BOOL}, ["enabled"]),
    "set_driver_region": shape({"garment_submesh_indices": _GARMENTS}, ["garment_submesh_indices"],
                               "limit the garments' binding to the selected body triangles"),
    "set_influence": shape({"weight": _d({"type": "number", "minimum": 0, "maximum": 1}, "Default 0."),
                            "garment_submesh_indices": _GARMENTS}, (),
                           "refit influence of the selected garment vertices"),
    "set_macro": shape({"macro_id": NAME, "value": {"type": "number", "minimum": -100, "maximum": 100},
                        "phase": _PHASE_END}, ["macro_id", "value"], "a body control's value"),
    "set_side_value": shape({"pair_id": NAME, "value": NUMBER,
                             "side": {"type": "string", "enum": ["both", "left", "right"], "default": "both"},
                             "phase": _PHASE_END}, ["pair_id", "value"], "one side of a paired control"),
    "set_symmetry": shape({"enabled": BOOL}, ["enabled"], "link or unlink the body's sides"),
    "set_value": shape({"definition_id": NAME, "value": _d(NUMBER, "Percent, clamped to the slider's range."),
                        "phase": {"type": "string", "enum": ["begin", "update", "end", "cancel"], "default": "end"},
                        "change_id": STRING}, ["definition_id", "value"], "a slider's value"),
}

# ----- Morph & Refit: refit ---------------------------------------------------------------
_FIT_SETTINGS = {
    "enabled": BOOL,
    "intensity_percent": {"type": "number", "minimum": 0, "maximum": 200},
    "mode": {"type": "string", "enum": ["surface", "rigid", "rigid_component"]},
    "clearance_percent": {"type": "number", "minimum": 0, "maximum": 5},
    "tightness_percent": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
    "skin_pull_percent": {"type": "number", "minimum": 0, "maximum": 100},
}
REFIT: dict[str, dict] = {
    "bind": shape({"submesh_indices": _d(PARTS, "Garment parts to bind (not the driver's).")}),
    "choose_archive": shape({"role": {"type": "string", "enum": ["body", "armor"]},
                             "archive_path": _d(PATH, "The file's path in the game archives (search_archive)."),
                             "source": STRING}, ["role", "archive_path"],
                            "Load Body or Load Armor from the game archives, without the picker"),
    "clear": NONE,
    "configure": shape({"submesh_indices": _d(PARTS, "Bound garment parts."), **_FIT_SETTINGS},
                       ["submesh_indices"], "Part fitting settings; only the fields given change"),
    "diagnostics": shape({"submesh_indices": {**PARTS, "minItems": 1, "maxItems": 128},
                          "sample_limit": {"type": "integer", "minimum": 1, "maximum": 4096},
                          "detail_limit": {"type": "integer", "minimum": 1, "maximum": 64}},
                         ["submesh_indices"], "measure the fit (reads only)"),
    "fit_to_body": shape({"reference_body": _d(BOOL, "Fit to the authored body (default true)."),
                          "body_weights": _d(BOOL, "Take the body's weights (default true).")}),
    "island_configure": shape({"islands": {**ISLANDS, "minItems": 1}, "inherit": BOOL, **_FIT_SETTINGS},
                              ["islands"], "override islands' settings, or inherit the part's again"),
    "load_mesh": shape({"role": {"type": "string", "enum": ["body", "armor"]},
                        "path": _d(PATH, "A local .pac, .pam, .pamlod, .obj or .glb file (Free Edit output).")},
                       ["role", "path"]),
    "restore_shape_apply": NONE,
    "restore_shape_cancel": NONE,
    "restore_shape_preview": shape({"path": _d(PATH, "A local unbaked .pac with the same parts."),
                                    "submesh_indices": PARTS, "islands": ISLANDS}, ["path"],
                                   "preview positions restored from a matching PAC"),
    "set_driver": shape({"submesh_indices": _d(PARTS, "The body (driver) parts.")}),
    "use_loaded_body": NONE,
}

# ----- Rig & Weights ----------------------------------------------------------------------
RIG: dict[str, dict] = {
    "select_bone": shape({"bone_index": _d(INT, "The skeleton bone, as mesh_panels' skeleton lists it.")},
                         ["bone_index"], "the bone the weight buttons work on"),
    "adjust_weight": shape({"delta": _d(NUMBER, "Signed change to the selected bone's weight.")}, ["delta"],
                           "on the selected vertices"),
    "normalize_weights": shape(text="on the selected vertices"),
    "transfer_weights": shape(text="on the selected vertices"),
}

# ----- Layers -----------------------------------------------------------------------------
_LAYER = _d(NAME, "A layer id, as mesh_panels' geometry_layers lists it.")
LAYER: dict[str, dict] = {
    "activate": shape({"layer_id": _LAYER}, ["layer_id"]),
    "rename": shape({"layer_id": _LAYER, "name": NAME}, ["layer_id", "name"]),
    "visibility": shape({"layer_id": _LAYER, "visible": _d(BOOL, "Default true.")}, ["layer_id"]),
    "move": shape({"layer_id": _LAYER, "direction": _d({"type": "integer"}, "Negative moves up, positive down.")},
                  ["layer_id"]),
    "copy": shape({"target": _d({"type": "string", "enum": ["vertex", "edge", "face"]},
                                "By default what the current selection holds.")},
                  (), "copies the current selection"),
    "paste": NONE,
    "delete": shape({"layer_id": _LAYER}, ["layer_id"]),
}

# ----- Cloth ------------------------------------------------------------------------------
CLOTH: dict[str, dict] = {
    "paint_set": shape({"value": {"type": "number", "minimum": 0, "maximum": 1},
                        "whole_model": _d(BOOL, "Paint every vertex, not only the selected ones.")}, ["value"],
                       "cloth influence on the selected vertices"),
    "pin_set": shape({"value": BOOL, "whole_model": _d(BOOL, "With value false: clear every pin.")}, ["value"],
                     "pins on the selected vertices"),
    "collision_input": shape({
        "role": {"type": "string", "enum": ["body", "head", "weapon"]},
        "archive_path": _d(PATH, "A .pabv (body, head) or .pac (weapon) in the game archives, as search_archive "
                                 "lists it."),
        "path": _d(PATH, "An absolute path to such a file on disk."),
        "source": {"type": "string", "enum": ["archive"]},
        "clear": _d(BOOL, "true: clear the preview's collision inputs."),
        "weapon_placement": {"type": "object", "additionalProperties": False, "required": ["offset", "rotation"],
                             "description": "Moves the weapon chosen before: offset and rotation (degrees).",
                             "properties": {"offset": VEC3, "rotation": VEC3}}},
        (), "{role, archive_path}, {role, path}, {clear: true} or {weapon_placement}"),
}

# ----- The Inspector's part options (replacement_*) -----------------------------------
PART_IDS = {"type": "array", "minItems": 1, "maxItems": 4096, "items": {"type": "string", "maxLength": 128},
            "description": "Part ids, as mesh_panels' replacement section lists them."}
RESET = _d(BOOL, "true: restore the source's own values.")
_UNIT = {"type": "number", "minimum": 0, "maximum": 1}
_POSITION = {"type": ["array", "null"], "minItems": 3, "maxItems": 3, "items": {"type": "number"}}
_SIZES = {"type": ["array", "null"], "minItems": 1, "maxItems": 3, "items": {"type": "number"},
          "description": "Sphere [r], capsule or cylinder [r, h], box [z, x, y]; null keeps them."}
_MASK = {"type": "object", "additionalProperties": False, "required": ["width", "height", "pixels"],
         "description": "{width, height, pixels: base64 of zlib-compressed 8-bit values}.",
         "properties": {"width": {"type": "integer", "minimum": 1, "maximum": 8192},
                        "height": {"type": "integer", "minimum": 1, "maximum": 8192},
                        "pixels": {"type": "string", "maxLength": 32 * 1024 * 1024}}}
_SHADER_CONTROLS = {
    "type": "object", "required": ["shader", "values"], "additionalProperties": False,
    "description": "Shader experiments for the parts: the shader family and its fields' values.",
    "properties": {
        "shader": {"type": "string", "enum": ["SkinnedMeshWing", "SkinnedMeshTornCloth_Ver2",
                                              "SkinnedMeshHairAnimatedUV", "SkinnedMeshAnisotropy",
                                              "SkinnedMeshPoster", "Dissolve", "Translucent",
                                              "SkinnedMeshTranslucent", "SkinnedMeshGlass",
                                              "SkinnedMeshTransparency", "SkinnedMeshEyeCover"]},
        "values": {"type": "object", "description": "{field: [numbers]}, each as long as the field's default (1 to "
                                                    "3) and in its range; fields left out keep the source's."},
        "transparency_mask": _MASK, "surface_response_mask": _MASK, "cutout_mask": _MASK,
        "coverage_mapping": {"type": "string", "enum": ["raw", "calibrated_v1"]},
        "colour_coverage": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "textures": {"type": "object", "description": "{parameter: sha256} of textures already stored; "
                                                      "texture_files is the way to give new ones."},
        "rebuild": _d(BOOL, "Rebuild the material (SkinnedMeshTransparency and SkinnedMeshGlass only)."),
        "force": _d(BOOL, "With rebuild."),
        "dropped_textures": {"type": "array", "maxItems": 32, "items": STRING,
                             "description": "With rebuild: texture rows to leave out (not _baseColorTexture)."}}}
PART: dict[str, dict] = {
    "shader_controls": shape({
        "part_ids": PART_IDS, "reset": RESET, "shader_controls": _SHADER_CONTROLS,
        "texture_files": {"type": "object", "description": "{parameter: path}: a DDS, or an image with power-of-two "
                                                           "sides from 4 to 8192, for a texture slot of the shader "
                                                           "(SkinnedMeshTransparency: _baseColorTexture, "
                                                           "_heightTexture; SkinnedMeshGlass and "
                                                           "SkinnedMeshTranslucent: _baseColorTexture, "
                                                           "_normalTexture). An empty path restores the source "
                                                           "texture."},
        "preset": {"type": "object", "additionalProperties": False, "required": ["action", "shader", "name"],
                   "description": "Save or delete a saved preset on this computer instead (the model is not "
                                  "changed).",
                   "properties": {"action": {"type": "string", "enum": ["save", "delete"]}, "shader": STRING,
                                  "name": {"type": "string", "minLength": 1, "maxLength": 48},
                                  "values": {"type": "object"}}}},
        (), "{part_ids, shader_controls, texture_files?}, {part_ids, reset: true} or {preset}"),
    "material_colours": shape({"part_ids": PART_IDS, "reset": RESET,
                               "colours": {"type": "object", "additionalProperties": {"type": "string"},
                                           "description": "{row: '#RRGGBB'}, 1 to 32 rows mesh_panels lists under "
                                                          "material_colours."}},
                              ["part_ids"], "parts sharing the material change together"),
    "emission": shape({"part_ids": PART_IDS, "reset": RESET, "emission": {
        "type": "object", "additionalProperties": False, "required": ["color", "intensity", "animation"],
        "properties": {"color": {"type": "array", "minItems": 3, "maxItems": 3, "items": _UNIT},
                       "intensity": {"type": "number", "minimum": 0, "maximum": 20},
                       "animation": {"type": "object", "additionalProperties": False,
                                     "required": ["flow_u", "flow_v", "pulse_frequency", "pulse_minimum"],
                                     "properties": {"flow_u": {"type": "number", "minimum": 0, "maximum": 10},
                                                    "flow_v": {"type": "number", "minimum": 0, "maximum": 10},
                                                    "pulse_frequency": {"type": "number", "minimum": 0,
                                                                        "maximum": 10},
                                                    "pulse_minimum": _UNIT}},
                       "rgb": {"type": ["object", "null"], "additionalProperties": False,
                               "required": ["intensity", "reveal", "softness", "inverse"],
                               "properties": {"intensity": _UNIT, "reveal": _UNIT,
                                              "softness": {"type": "number", "minimum": 0.001, "maximum": 1},
                                              "inverse": BOOL}}}}}, ["part_ids"]),
    "translucency": shape({"part_ids": PART_IDS, "reset": RESET,
                           "translucency": _d({"type": "array", "minItems": 2, "maxItems": 2, "items": _UNIT},
                                              "[thickness, extinction]."),
                           "translucency_surface": _d({"type": ["array", "null"], "minItems": 2, "maxItems": 2,
                                                       "items": {"type": ["number", "null"], "minimum": 0,
                                                                 "maximum": 1}},
                                                      "[roughness, metallic]; null keeps the surface.")},
                          ["part_ids"]),
    "jiggle": shape({"part_ids": PART_IDS, "reset": RESET,
                     "rule": {"type": "object", "additionalProperties": False, "required": ["below_y"],
                              "properties": {"below_y": _d({"type": ["number", "null"]},
                                                           "Only vertices below this height; null for all."),
                                             "retained": _UNIT,
                                             "bone_retained": _d({"type": "array", "maxItems": 0},
                                                                 "As mesh_panels reads it; this command takes "
                                                                 "none (use bone_slots).")}},
                     "bone_slots": _d({"type": "array", "minItems": 1, "maxItems": 4096, "items": INT},
                                      "Bone regions' slots (mesh_panels' jiggle); then below_y is null.")},
                    ["part_ids"]),
    "physics_profile": shape({"group_id": _d(NAME, "A group id from mesh_panels' physics_profiles."),
                              "reset": RESET,
                              "rule": {"type": "object", "additionalProperties": False,
                                       "required": ["variant", "source_profile", "source_path", "source_sha256",
                                                    "values"],
                                       "description": "The source fields as one of mesh_panels' physics_profiles "
                                                      "sources gives them, and 1 to 14 values (StretchingStiffness, "
                                                      "BendingStiffness, Damping, Gravity, SolverIterationCount, "
                                                      "IsCloak ...).",
                                       "properties": {"variant": STRING, "source_profile": STRING,
                                                      "source_path": STRING, "source_sha256": STRING,
                                                      "values": {"type": "object"}}}}, ["group_id"]),
    "collision_volumes": shape({
        "source": _d(STRING, "'model' (the PAC's own set) or a loaded body or head PABV's source."),
        "reset": RESET,
        "changes": {"type": "array", "maxItems": 256,
                    "items": {"type": "object", "additionalProperties": False,
                              "required": ["ordinal", "removed", "parameters", "position"],
                              "properties": {"ordinal": {"type": "integer", "minimum": 0, "maximum": 65535},
                                             "removed": BOOL, "parameters": _SIZES, "position": _POSITION}}},
        "copies": {"type": "array", "maxItems": 256,
                   "items": {"type": "object", "additionalProperties": False,
                             "required": ["template", "parameters", "position"],
                             "properties": {"template": {"type": "integer", "minimum": 0, "maximum": 65535},
                                            "parameters": _SIZES, "position": _POSITION}}}},
        ["source"], "replaces that source's whole edit"),
    "weapon_collisions": shape({"enabled": _d(BOOL, "true makes colliders; false restores the source's.")},
                               ["enabled"]),
    "cloth": shape({"part_ids": PART_IDS, "reset": RESET,
                    "rule": {"type": "object", "additionalProperties": False,
                             "required": ["amount", "fixed_above", "fade"],
                             "properties": {"amount": _UNIT, "fixed_above": {"type": ["number", "null"]},
                                            "fade": {"type": "number", "minimum": 0}}}}, ["part_ids"]),
    "guides": shape({"part_ids": PART_IDS, "reset": RESET,
                     "source_lod": {"type": "integer", "minimum": 0, "maximum": 3},
                     "fixed_above": {"type": ["number", "null"]}, "reduce_skinning": BOOL, "use_pins": BOOL},
                    ["part_ids"]),
    "islands": shape({"part_id": NAME, "faces": {"type": "array", "minItems": 1, "maxItems": 200000, "items": INT},
                      "included": BOOL}, ["part_id", "faces", "included"], "whole islands only"),
    "include": shape({"part_ids": PART_IDS, "included": BOOL}, ["part_ids", "included"]),
    "fit": shape(text="Import Replacement's Fit"),
    "compare": shape({"mode": {"type": "string", "enum": ["edit", "original", "output"]}}, (),
                     "what the view shows"),
    "reset": shape(text="Import Replacement's Reset"),
}

# ----- Topology and mesh actions: their params ----------------------------------------------
_UV2 = {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"}}
TOPOLOGY: dict[str, dict] = {
    **{name: NONE for name in ("subdivide", "duplicate", "edge_split", "split", "dissolve", "bridge", "fill",
                               "merge", "separate")},
    "delete": shape({"delete_parts": _d(BOOL, "Delete whole selected parts (Free Edit only).")}),
    "refine_smooth": shape({"smooth_strength": _UNIT,
                            "smooth_iterations": {"type": "integer", "minimum": 1, "maximum": 12}}),
    "extrude": shape({"offset": VEC3}),
    "inset": shape({"amount": {"type": "number", "minimum": 0, "maximum": 0.95}}),
    "loop_cut": shape({"cuts": {"type": "integer", "minimum": 1, "maximum": 16},
                       "factor": _d({"type": "number", "minimum": 0, "maximum": 1}, "With one cut.")}),
    "weld": shape({"threshold": {"type": "number", "minimum": 0}}),
}
_DISTANCE = {"type": "number", "minimum": 0}
_ALIGN = {"type": ["string", "number"],
          "description": "min, left, bottom, max, right, top, center, middle, or a number."}
MESH_ACTION: dict[str, dict] = {
    **{name: NONE for name in ("delete_loose_vertices", "compact_orphans", "fix_winding", "fill_holes",
                               "recalculate_normals", "generate_tangents", "flip_normals", "sharpen_normals",
                               "soften_normals", "weighted_normals", "copy_normals")},
    "mirror": shape({"axis": {"type": "string", "enum": ["x", "y", "z"]}, "in_place": BOOL}),
    "remove_doubles": shape({"threshold": _DISTANCE, "distance": _DISTANCE, "merge_distance": _DISTANCE}),
    "transform": shape({"translate": VEC3, "rotate_degrees": VEC3, "scale": VEC3, "pivot": VEC3,
                        "recompute_normals": BOOL}),
    "uv_transform": shape({
        "offset": _UV2, "scale": _UV2, "rotate": NUMBER, "rotate_degrees": NUMBER, "pivot": _UV2,
        "flip_u": BOOL, "flip_v": BOOL, "uv_island": BOOL,
        "selection_mode": {"type": "string", "enum": ["island", "uv_island"]},
        "normalize": BOOL, "target_min": _UV2, "target_max": _UV2, "align_u": _ALIGN, "align_v": _ALIGN,
        "projection": {"type": "string", "enum": ["planar", "xy", "xz", "yz", "box", "cube", "cylindrical",
                                                  "cylinder"]},
        "plane": {"type": "string", "enum": ["xy", "xz", "yz"]}, "axis": {"type": "string", "enum": ["x", "y", "z"]},
        "pack": BOOL, "pack_columns": INT, "padding": _DISTANCE,
        "snap_grid": {"type": ["number", "array"], "items": {"type": "number"}},
        "snap_pixels": BOOL, "texture_width": _DISTANCE, "texture_height": _DISTANCE, "texture_size": _UV2,
        "auto_uv": BOOL, "resolution": INT, "allow_topology_change": BOOL, "fallback_projection": STRING}),
}

#: The panel families, by the names ``mesh_edit_tools.PANEL_COMMANDS`` uses. Hair Tools' shapes are not here.
PANELS: dict[str, dict[str, dict]] = {"rig": RIG, "morph": MORPH, "refit": REFIT, "cloth": CLOTH, "layer": LAYER,
                                      "replacement": PART}
#: The ``params`` of ``mesh.topology`` and ``mesh.mesh_action``.
PARAMS: dict[str, dict[str, dict]] = {"topology": TOPOLOGY, "mesh_action": MESH_ACTION}


def _union(table: Mapping[str, dict]) -> dict[str, object]:
    """Every field any command of ``table`` takes, typed; a field typed differently by two commands
    takes the types of both, and its command's own shape is checked by :func:`check`."""

    fields: dict[str, list] = {}
    for command in table.values():
        for name, schema in command["properties"].items():
            fields.setdefault(name, []).append(schema)
    properties: dict[str, object] = {}
    for name, schemas in fields.items():
        first = schemas[0]
        if all(schema == first for schema in schemas):
            properties[name] = dict(first)
            continue
        types: list[str] = []
        for schema in schemas:
            kinds = schema.get("type")
            for kind in kinds if isinstance(kinds, list) else [kinds]:
                if kind and kind not in types:
                    types.append(kind)
        properties[name] = {"type": types if len(types) > 1 else types[0],
                            "description": "Its shape depends on the action (see the tool's description)."}
    return {"type": "object", "properties": properties, "additionalProperties": False}


def union_schema(table: Mapping[str, dict], what: str) -> dict[str, object]:
    schema = _union(table)
    schema["description"] = what
    return schema


def _field_list(command: dict) -> str:
    required = set(command["required"])
    names = [name if name in required else f"{name}?" for name in command["properties"]]
    text = "{" + ", ".join(names) + "}" if names else "{}"
    return f"{text} ({command['text']})" if command.get("text") and command["text"] != "no arguments" else text


def actions_text(table: Mapping[str, dict]) -> str:
    """Each command with its fields (? marks the optional ones), for a tool's description."""

    return "; ".join(f"{name} {_field_list(command)}" for name, command in table.items()) + "."


def check(table: Mapping[str, dict], name: str, arguments: Mapping[str, object], where: str) -> None:
    """Refuse ``arguments`` that are not ``name``'s own shape, before anything is sent."""

    from cdmw.mcp.schema import validate_arguments

    command = table[name]
    fields = command["properties"]
    extra = sorted(set(arguments) - set(fields))
    if extra:
        allowed = ", ".join(fields) or "no fields"
        raise ToolError(INVALID_ARGUMENTS, f"{where} {name} takes {allowed}, not {extra[0]!r}.")
    schema = {"type": "object", "properties": fields, "required": command["required"],
              "additionalProperties": False}
    try:
        validate_arguments(dict(arguments), schema)
    except ToolError as error:
        raise ToolError(INVALID_ARGUMENTS, f"{where} {name}: {error}") from None


__all__ = ["PANELS", "PARAMS", "actions_text", "check", "union_schema"]
