"""PAC/XML texture-role rules independent of corpus I/O."""

from __future__ import annotations

import re
from pathlib import PurePosixPath


def infer_pac_xml_texture_role(parameter_name: str, texture_path: str = "") -> str:
    """Resolve PAC/XML texture semantics with parameter evidence before suffix aliases."""

    name = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").casefold())
    path = str(texture_path or "").replace("\\", "/").casefold()
    if "flow" in name or "hairdirection" in name or "ssdm" in name:
        return "flow"
    if "wrinklemask" in name:
        return "wrinkle_mask"
    if "wrinklecolor" in name:
        return "wrinkle_color"
    if "normal" in name or path.endswith("_n.dds"):
        return "normal"
    if path.endswith("_f.dds"):
        return "flow"
    if "pupil" in name:
        return "pupil"
    if "iris" in name:
        return "iris"
    if "alpha" in name or "opacity" in name or path.endswith("_alpha.dds"):
        return "opacity"
    if "height" in name or "displacement" in name or path.endswith(("_disp.dds", "_h.dds")):
        return "height"
    if "detailmask" in name or path.endswith("_mg.dds"):
        return "detail_mask"
    if "colorblendingmask" in name or "material" in name or path.endswith(("_ma.dds", "_m.dds", "_sp.dds")):
        return "material_mask"
    if "emissive" in name or path.endswith("_emi.dds"):
        return "emissive"
    if name == "masktexture" or name.endswith("masktexture"):
        return "material_mask" if not path else "mask"
    if any(token in name for token in ("overlaycolor", "basecolor", "diffuse", "albedo", "rgbtexture")):
        return "base"
    return "unknown"


def pac_xml_texture_alias_matches_parameter(parameter_name: str, texture_path: str) -> bool:
    """Return true when a corpus-shaped short suffix is disambiguated by its wrapper parameter."""

    stem = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.casefold()
    suffix = stem.rsplit("_", 1)[-1]
    allowed_roles = {
        "f": {"flow", "normal"},
        "h": {"height"},
        "m": {"material_mask"},
    }.get(suffix)
    if allowed_roles is None:
        return False
    parameter_role = infer_pac_xml_texture_role(parameter_name)
    return parameter_role in allowed_roles


__all__ = ["infer_pac_xml_texture_role", "pac_xml_texture_alias_matches_parameter"]
