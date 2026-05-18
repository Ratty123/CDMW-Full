"""Read-only analysis for known-good loose mod material recipes."""

from __future__ import annotations

import json
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

from .asset_replacement import infer_cd_texture_role_from_path
from .static_mesh_replacer import StaticDonorMaterialPlan, StaticDonorMaterialTextureBinding


@dataclass(frozen=True, slots=True)
class WorkingModTextureBinding:
    parameter_name: str
    texture_path: str
    slot_kind: str
    semantic_subtype: str = ""
    source_member_path: str = ""
    source_path: str = ""


@dataclass(frozen=True, slots=True)
class WorkingModScalarParameter:
    parameter_kind: str
    parameter_name: str
    value: str = ""
    numeric_value: Optional[float] = None


@dataclass(frozen=True, slots=True)
class WorkingModMaterialRecipe:
    sidecar_path: str
    sidecar_text: str = ""
    material_name: str = ""
    submesh_name: str = ""
    shader_family: str = ""
    texture_bindings: tuple[WorkingModTextureBinding, ...] = ()
    scalar_parameters: tuple[WorkingModScalarParameter, ...] = ()
    glow_active: bool = False
    glow_status: str = "missing"
    emissive_color: str = ""
    emissive_intensity: float = 0.0
    has_emissive_texture: bool = False
    has_dedicated_emi_dds: bool = False
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkingModPackageAnalysis:
    package_path: str
    package_kind: str
    crimsonforge_like: bool = False
    manifest: Mapping[str, object] = field(default_factory=dict)
    modinfo: Mapping[str, object] = field(default_factory=dict)
    pac_paths: tuple[str, ...] = ()
    sidecar_paths: tuple[str, ...] = ()
    texture_paths: tuple[str, ...] = ()
    icon_paths: tuple[str, ...] = ()
    recipes: tuple[WorkingModMaterialRecipe, ...] = ()
    warnings: tuple[str, ...] = ()


_TEXTURE_BLOCK_RE = re.compile(
    r"<MaterialParameterTexture\b(?P<attrs>[^>]*)>(?P<body>.*?)</MaterialParameterTexture>",
    flags=re.IGNORECASE | re.DOTALL,
)
_PARAM_BLOCK_RE = re.compile(
    r"<(?P<tag>MaterialParameter(?:Float|Color|Byte4|BitFlag32|Int|Integer|Bool|Boolean))\b(?P<attrs>[^>]*)/?>",
    flags=re.IGNORECASE | re.DOTALL,
)
_WRAPPER_RE = re.compile(
    r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
    flags=re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(r"([A-Za-z0-9_:.-]+)\s*=\s*\"([^\"]*)\"", flags=re.IGNORECASE)
_TEXTURE_PATH_RE = re.compile(
    r"<ResourceReferencePath_ITexture\b[^>]*\b_path=\"(?P<path>[^\"]*)\"",
    flags=re.IGNORECASE | re.DOTALL,
)


def analyze_working_mod_package(path: Path | str) -> WorkingModPackageAnalysis:
    """Inspect a loose mod directory/archive without extracting assets into the app."""

    package_path = Path(path).expanduser()
    warnings: list[str] = []
    try:
        members = _read_package_members(package_path, warnings)
    except Exception as exc:
        return WorkingModPackageAnalysis(
            package_path=str(package_path),
            package_kind=package_path.suffix.lower().lstrip(".") or ("directory" if package_path.is_dir() else "file"),
            warnings=(f"package read failed: {exc}",),
        )

    normalized_names = tuple(sorted(members))
    manifest = _load_json_member(members, "manifest.json")
    modinfo = _load_json_member(members, "modinfo.json")
    pac_paths = tuple(name for name in normalized_names if name.lower().endswith(".pac"))
    sidecar_paths = tuple(name for name in normalized_names if name.lower().endswith((".pac_xml", ".pam_xml", ".pamlod_xml")))
    texture_paths = tuple(name for name in normalized_names if name.lower().endswith(".dds") and "/texture" in name.lower())
    icon_paths = tuple(name for name in normalized_names if name.lower().endswith(".dds") and "/ui/" in f"/{name.lower()}")
    texture_member_by_basename = {PurePosixPath(name).name.lower(): name for name in texture_paths}

    recipes: list[WorkingModMaterialRecipe] = []
    for sidecar_path in sidecar_paths:
        try:
            sidecar_text = members[sidecar_path].decode("utf-8-sig", errors="replace")
        except Exception as exc:
            warnings.append(f"{sidecar_path}: sidecar decode failed: {exc}")
            continue
        recipes.extend(_extract_material_recipes(sidecar_path, sidecar_text, texture_member_by_basename, package_path))

    crimsonforge_like = bool(
        ("manifest.json" in {PurePosixPath(name).name.lower() for name in normalized_names})
        and ("modinfo.json" in {PurePosixPath(name).name.lower() for name in normalized_names})
        and any(name.lower().startswith("files/") or "/files/" in name.lower() for name in normalized_names)
        and sidecar_paths
        and texture_paths
    )
    return WorkingModPackageAnalysis(
        package_path=str(package_path),
        package_kind="directory" if package_path.is_dir() else package_path.suffix.lower().lstrip("."),
        crimsonforge_like=crimsonforge_like,
        manifest=manifest,
        modinfo=modinfo,
        pac_paths=pac_paths,
        sidecar_paths=sidecar_paths,
        texture_paths=texture_paths,
        icon_paths=icon_paths,
        recipes=tuple(recipes),
        warnings=tuple(warnings),
    )


def donor_plan_from_working_mod_recipe(
    recipe: WorkingModMaterialRecipe,
    *,
    target_material_name: str,
    patch_mode: str = "material_behavior",
    enabled: bool = True,
) -> StaticDonorMaterialPlan:
    """Convert an analyzed recipe into the existing donor-material plan shape."""

    return StaticDonorMaterialPlan(
        target_material_name=str(target_material_name or "").strip(),
        donor_sidecar_path=recipe.sidecar_path,
        donor_sidecar_text=recipe.sidecar_text,
        donor_sidecar_kind="pac_xml" if recipe.sidecar_path.lower().endswith(".pac_xml") else "",
        donor_material_name=recipe.material_name,
        donor_submesh_name=recipe.submesh_name,
        donor_shader_family=recipe.shader_family,
        patch_mode=patch_mode,
        texture_bindings=[
            StaticDonorMaterialTextureBinding(
                parameter_name=binding.parameter_name,
                texture_path=binding.texture_path,
                slot_kind=binding.slot_kind,
                semantic_subtype=binding.semantic_subtype,
                source_path=binding.source_path,
            )
            for binding in recipe.texture_bindings
        ],
        donor_anchor_texture_paths=[binding.texture_path for binding in recipe.texture_bindings],
        enabled=enabled,
    )


def _read_package_members(package_path: Path, warnings: list[str]) -> dict[str, bytes]:
    if package_path.is_dir():
        members: dict[str, bytes] = {}
        for child in package_path.rglob("*"):
            if child.is_file():
                try:
                    members[child.relative_to(package_path).as_posix()] = child.read_bytes()
                except OSError as exc:
                    warnings.append(f"{child}: read failed: {exc}")
        return members
    suffix = package_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(package_path) as archive:
            return {
                info.filename.replace("\\", "/"): archive.read(info)
                for info in archive.infolist()
                if not info.is_dir()
            }
    if suffix == ".7z":
        return _read_7z_members_with_tar(package_path, warnings)
    raise ValueError(f"unsupported package type: {package_path.suffix or package_path}")


def _read_7z_members_with_tar(package_path: Path, warnings: list[str]) -> dict[str, bytes]:
    list_result = subprocess.run(
        ["tar", "-tf", str(package_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if list_result.returncode != 0:
        raise ValueError((list_result.stderr or "tar could not list 7z archive").strip())
    members: dict[str, bytes] = {}
    for raw_name in list_result.stdout.splitlines():
        name = raw_name.strip().replace("\\", "/")
        if not name or name.endswith("/"):
            continue
        lowered = name.lower()
        if not (
            lowered.endswith((".json", ".pac_xml", ".pam_xml", ".pamlod_xml"))
            or (lowered.endswith(".dds") and ("/texture" in lowered or "/ui/" in f"/{lowered}"))
            or lowered.endswith(".pac")
        ):
            continue
        extract_result = subprocess.run(
            ["tar", "-xOf", str(package_path), name],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if extract_result.returncode != 0:
            warnings.append(f"{name}: tar extract failed")
            continue
        members[name] = extract_result.stdout
    return members


def _load_json_member(members: Mapping[str, bytes], basename: str) -> Mapping[str, object]:
    wanted = basename.lower()
    for name, payload in members.items():
        if PurePosixPath(name).name.lower() != wanted:
            continue
        try:
            data = json.loads(payload.decode("utf-8-sig", errors="replace"))
        except Exception:
            return {}
        return data if isinstance(data, Mapping) else {}
    return {}


def _extract_material_recipes(
    sidecar_path: str,
    sidecar_text: str,
    texture_member_by_basename: Mapping[str, str],
    package_path: Path,
) -> list[WorkingModMaterialRecipe]:
    wrappers = list(_WRAPPER_RE.finditer(sidecar_text))
    if not wrappers:
        wrappers = [None]  # type: ignore[list-item]
    recipes: list[WorkingModMaterialRecipe] = []
    for wrapper in wrappers:
        block = wrapper.group(0) if wrapper is not None else sidecar_text
        wrapper_attrs = _attrs_dict(wrapper.group("attrs") if wrapper is not None else "")
        texture_bindings = _extract_texture_bindings(block, texture_member_by_basename, package_path)
        scalar_parameters = _extract_scalar_parameters(block)
        shader_family = _extract_shader_family(block)
        submesh_name = _first_attr(wrapper_attrs, "_subMeshName", "subMeshName", "PrimitiveName")
        material_name = _first_attr(_attrs_dict(_first_material_attrs(block)), "_materialName", "MaterialName", "Name")
        recipe = _build_recipe(
            sidecar_path=sidecar_path,
            sidecar_text=block,
            material_name=material_name,
            submesh_name=submesh_name,
            shader_family=shader_family,
            texture_bindings=tuple(texture_bindings),
            scalar_parameters=tuple(scalar_parameters),
        )
        if recipe.texture_bindings or recipe.scalar_parameters or recipe.shader_family:
            recipes.append(recipe)
    return recipes


def _build_recipe(
    *,
    sidecar_path: str,
    sidecar_text: str,
    material_name: str,
    submesh_name: str,
    shader_family: str,
    texture_bindings: tuple[WorkingModTextureBinding, ...],
    scalar_parameters: tuple[WorkingModScalarParameter, ...],
) -> WorkingModMaterialRecipe:
    emissive_textures = tuple(
        binding for binding in texture_bindings if "emissive" in binding.semantic_subtype or "emissive" in binding.parameter_name.lower()
    )
    emissive_color = ""
    emissive_intensity_values: list[float] = []
    for parameter in scalar_parameters:
        key = parameter.parameter_name.lower()
        if "emissivecolor" in key and parameter.value:
            emissive_color = parameter.value
        if "emissiveintensity" in key and parameter.numeric_value is not None:
            emissive_intensity_values.append(float(parameter.numeric_value))
    intensity = max(emissive_intensity_values) if emissive_intensity_values else 0.0
    has_emi = any(PurePosixPath(binding.texture_path).name.lower().endswith("_emi.dds") for binding in texture_bindings)
    glow_status = "active" if intensity > 0.0 else ("disabled" if emissive_textures or emissive_intensity_values else "missing")
    diagnostics: list[str] = []
    if shader_family.lower().find("emissive") >= 0:
        diagnostics.append("emissive shader family")
    if emissive_textures:
        diagnostics.append("emissive intensity texture present")
    if emissive_intensity_values:
        diagnostics.append(f"emissive intensity={intensity:g}")
    if has_emi:
        diagnostics.append("dedicated _emi.dds mask")
    return WorkingModMaterialRecipe(
        sidecar_path=sidecar_path,
        sidecar_text=sidecar_text,
        material_name=material_name,
        submesh_name=submesh_name,
        shader_family=shader_family,
        texture_bindings=texture_bindings,
        scalar_parameters=scalar_parameters,
        glow_active=bool(intensity > 0.0),
        glow_status=glow_status,
        emissive_color=emissive_color,
        emissive_intensity=float(intensity),
        has_emissive_texture=bool(emissive_textures),
        has_dedicated_emi_dds=has_emi,
        diagnostics=tuple(diagnostics),
    )


def _extract_texture_bindings(
    block: str,
    texture_member_by_basename: Mapping[str, str],
    package_path: Path,
) -> list[WorkingModTextureBinding]:
    bindings: list[WorkingModTextureBinding] = []
    for match in _TEXTURE_BLOCK_RE.finditer(block):
        attrs = _attrs_dict(match.group("attrs"))
        parameter_name = _parameter_name(attrs)
        path_match = _TEXTURE_PATH_RE.search(match.group("body"))
        texture_path = str(path_match.group("path") if path_match else "").replace("\\", "/").strip()
        if not texture_path:
            continue
        slot_kind, semantic_subtype = _slot_for_parameter(parameter_name, texture_path)
        member_path = texture_member_by_basename.get(PurePosixPath(texture_path).name.lower(), "")
        source_path = ""
        if package_path.is_dir() and member_path:
            source = package_path / Path(member_path)
            if source.is_file():
                source_path = str(source)
        bindings.append(
            WorkingModTextureBinding(
                parameter_name=parameter_name,
                texture_path=texture_path,
                slot_kind=slot_kind,
                semantic_subtype=semantic_subtype,
                source_member_path=member_path,
                source_path=source_path,
            )
        )
    return bindings


def _extract_scalar_parameters(block: str) -> list[WorkingModScalarParameter]:
    parameters: list[WorkingModScalarParameter] = []
    for match in _PARAM_BLOCK_RE.finditer(block):
        tag = match.group("tag")
        attrs = _attrs_dict(match.group("attrs"))
        parameter_name = _parameter_name(attrs)
        value = _first_attr(attrs, "Value", "_value", "value")
        numeric: Optional[float] = None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = None
        parameters.append(
            WorkingModScalarParameter(
                parameter_kind=tag,
                parameter_name=parameter_name,
                value=value,
                numeric_value=numeric,
            )
        )
    return parameters


def _slot_for_parameter(parameter_name: str, texture_path: str) -> tuple[str, str]:
    key = f"{parameter_name} {texture_path}".lower()
    if "emissive" in key or "_emi" in key or "glow" in key:
        return "emissive", "emissive_intensity"
    if "normal" in key or texture_path.lower().endswith("_n.dds"):
        return "normal", ""
    if "height" in key or "disp" in key:
        return "height", "height"
    if "detailmask" in key or "colorblendingmask" in key or texture_path.lower().endswith("_mg.dds"):
        return "detail_mask", "detail_mask"
    if "material" in key or texture_path.lower().endswith(("_ma.dds", "_sp.dds")):
        return "material", "material_mask"
    role = infer_cd_texture_role_from_path(texture_path)
    if role:
        return role, role
    return "base", "color"


def _extract_shader_family(block: str) -> str:
    material_attrs = _attrs_dict(_first_material_attrs(block))
    for key in ("_materialName", "MaterialName", "Name", "shader", "shaderFamily"):
        value = str(material_attrs.get(key.lower(), "") or "").strip()
        if value:
            return value
    match = re.search(r"SkinnedMesh[A-Za-z0-9_]*", block)
    return match.group(0) if match else ""


def _first_material_attrs(block: str) -> str:
    match = re.search(r"<Material\b([^>]*)>", block, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _attrs_dict(text: str) -> dict[str, str]:
    return {match.group(1).lower(): match.group(2) for match in _ATTR_RE.finditer(str(text or ""))}


def _parameter_name(attrs: Mapping[str, str]) -> str:
    return _first_attr(attrs, "_name", "StringItemID", "Name", "ItemID")


def _first_attr(attrs: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = str(attrs.get(name.lower(), "") or "").strip()
        if value:
            return value
    return ""


__all__ = [
    "WorkingModMaterialRecipe",
    "WorkingModPackageAnalysis",
    "WorkingModScalarParameter",
    "WorkingModTextureBinding",
    "analyze_working_mod_package",
    "donor_plan_from_working_mod_recipe",
]
