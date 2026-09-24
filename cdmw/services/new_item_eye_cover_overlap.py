"""Add the opt-in global EyeCover experiment to the ordinary New Item plan."""
import hashlib
import json
import xml.etree.ElementTree as ET

from cdmw.core.eye_cover_overlap import RENDERPASS_PATH, rewrite_eye_cover_overlap
from cdmw.domain.mesh.shader_controls import EYE_COVER, EYE_COVER_OVERLAP_FIELD


def plan_eye_cover_overlap(planner):
    choices = (appearance.shader_controls for appearance in planner.spec.variants) if planner.spec.variants is not None else (planner.spec.shader_controls,)
    enabled = any(controls.shader == EYE_COVER.shader and dict(controls.values).get(EYE_COVER_OVERLAP_FIELD) == (1.,)
                  for group in choices for _, controls in group)
    if not enabled:
        if planner.snapshot.base_manifest.get("eye_cover_overlap_test"):
            planner.manifest["eye_cover_overlap_test"] = dict(planner.snapshot.base_manifest["eye_cover_overlap_test"])
            planner.warnings.append("The base mod already includes the global EyeCover overlap test. Use a base without that test for an off comparison.")
        return
    from cdmw.services.new_item_planning import NewItemPlanError

    planner.check()
    if not planner.snapshot.has_entry(RENDERPASS_PATH):
        raise NewItemPlanError("The global EyeCover overlap test requires the game's character render definition.")
    original = planner.snapshot.payload(RENDERPASS_PATH)
    try:
        changed = rewrite_eye_cover_overlap(original)
    except (ValueError, ET.ParseError) as exc:
        raise NewItemPlanError(f"Cannot prepare the global EyeCover overlap test: {exc}") from exc
    planner.check()
    planner.patch(planner.snapshot.entry(RENDERPASS_PATH), changed, "Global EyeCover overlap test (experimental)")
    planner.warnings.append("Global EyeCover overlap test: affects all EyeCover materials, including eyes. Render order and lighting remain unverified; test in game. Remove this test mod for the stock comparison.")
    planner.manifest["eye_cover_overlap_test"] = {
        "version": 1, "scope": "all_eye_cover_materials", "path": RENDERPASS_PATH,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "output_sha256": hashlib.sha256(changed).hexdigest(),
    }


def retire_exported_overlap_test(plan, root, payload, *, stop_event=None):
    """Retire only an unchanged test owned by this item on DMM re-export.

Ordinary render overrides and experiments inherited through an explicit base
stay intact. Unknown ownership must not silently leave an off comparison on.
"""
    if plan.manifest.get("eye_cover_overlap_test"):
        return False
    try:
        if rewrite_eye_cover_overlap(payload) != payload:
            return False
    except (ValueError, ET.ParseError):
        return False
    from cdmw.core.mod_export_history import mod_metadata_path
    metadata = mod_metadata_path(root, "new-item.json", stop_event=stop_event)
    if metadata.is_file() and not metadata.is_symlink() and metadata.stat().st_size <= 8 * 1024 * 1024:
        try:
            previous = json.loads(metadata.read_bytes())
            recorded = previous["eye_cover_overlap_test"]
            if (previous["item_key"] == plan.spec.item_key and recorded["version"] == 1
                    and recorded["path"] == RENDERPASS_PATH
                    and recorded["output_sha256"] == hashlib.sha256(payload).hexdigest()):
                return True
        except (ValueError, KeyError, TypeError):
            pass
    raise ValueError("Cannot turn off the EyeCover overlap test in this existing package safely. Export to a new mod folder for the off comparison.")
