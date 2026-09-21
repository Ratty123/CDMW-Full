"""Read an FBX by asking Blender to hand it over as glTF, when the reader points us at one.

The studio reads glTF, GLB, OBJ and DAE with its own readers, and does not read FBX. The
container would be easy enough -- binary FBX is a typed node tree and a ninety-line probe
walks one -- but the semantics are not: the transform stack (pre- and post-rotation,
pivots, the geometric offset), the layer-element mapping modes, and the axis and unit
conversion in `GlobalSettings` are where an FBX arrives rotated, mirrored or a hundred
times too large. Getting those right for the long tail is Blender's job, and Blender does
it correctly because it has to.

So FBX is supported *through* Blender, and only when the reader says where Blender is.
Nothing here searches the machine and quietly uses what it finds: a conversion that
happened without being asked for is a conversion nobody can account for when the result
looks wrong. :func:`likely_blender_executables` offers candidates for a file dialog to
open on; the path that is used is the one the reader chose.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from cdmw.models import ModelPreviewData
    from cdmw.modding.scene_import_result_ops import SceneImportResult

__all__ = [
    "FBX_EXTENSION",
    "BlenderConversion",
    "BlenderNotConfigured",
    "apply_fbx_sibling_texture_factors",
    "convert_fbx_to_glb",
    "describe_blender",
    "is_blender_executable",
    "likely_blender_executables",
]

FBX_EXTENSION = ".fbx"

#: How long a conversion may take before it is abandoned. Blender starts in a second or
#: two and writes a weapon in a few more; a minute is a hang, not a big file.
_TIMEOUT_SECONDS = 180

#: What Blender is told to do: import the FBX, export the whole scene as one GLB with its
#: textures embedded, and say how much came through. `--factory-startup` so a reader's own
#: add-ons and preferences cannot change the result.
_SCRIPT = """
import bpy, json, sys
from pathlib import Path

source, target = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=source)
source_path = Path(source)
target_path = Path(target)
image_search_roots = (
    source_path.parent,
    source_path.parent / "textures",
    source_path.parent.parent / "textures",
    target_path.parent / "textures",
)
for image in bpy.data.images:
    if image.users and not image.has_data:
        wanted = Path(image.filepath).name.casefold()
        if not wanted:
            continue
        for root in image_search_roots:
            try:
                candidate = next(
                    (path for path in root.iterdir() if path.is_file() and path.name.casefold() == wanted),
                    None,
                )
            except OSError:
                continue
            if candidate is None:
                continue
            image.filepath = str(candidate)
            try:
                image.reload()
            except (OSError, RuntimeError):
                pass
            if image.has_data:
                break
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
vertices = sum(len(o.data.vertices) for o in meshes)
materials = sorted({s.material.name for o in meshes for s in o.material_slots if s.material})
bpy.ops.export_scene.gltf(
    filepath=target,
    export_format="GLB",
    export_texcoords=True,
    export_normals=True,
    export_materials="EXPORT",
    export_yup=True,
    use_selection=False,
)
images = sorted({i.name for i in bpy.data.images if i.users and i.has_data})
print("CDMW_FBX_RESULT " + json.dumps({
    "objects": len(meshes),
    "vertices": vertices,
    "materials": materials,
    "images": images,
}))
"""


class BlenderNotConfigured(RuntimeError):
    """Raised when an FBX needs converting and no Blender has been pointed at."""


def apply_fbx_sibling_texture_factors(scene_result: SceneImportResult, preview_model: ModelPreviewData) -> None:
    """Use loose PBR maps without multiplying them by converted legacy FBX scalars.

    Compare the converted material with the resolved preview before its bindings
    are copied back. Only newly attached colour/roughness/metallic channels get
    identity factors; linked channels and materials without maps keep their values.
    """
    from cdmw.models import PreviewMaterialParameterInput
    from cdmw.services.mesh_dotnet_material_channels import _dotnet_resolved_texture_channels

    submeshes = tuple(scene_result.mesh.submeshes)
    recovered_slots: dict[int, tuple[tuple[str, Path], ...]] = {}
    for preview in preview_model.meshes:
        index = preview.source_submesh_index
        if not 0 <= index < len(submeshes):
            continue
        resolved = _dotnet_resolved_texture_channels(preview)
        added_channels = resolved.keys() - _dotnet_resolved_texture_channels(submeshes[index]).keys()
        slots = tuple(
            (channel, Path(resolved[channel]))
            for channel in ("base", "normal", "material", "roughness", "metallic", "emissive", "height", "occlusion")
            if channel in added_channels
            and not (channel in {"roughness", "metallic"} and resolved[channel] == resolved.get("material"))
        )
        if slots:
            recovered_slots[index] = slots
            submeshes[index].texture_slots = tuple(getattr(submeshes[index], "texture_slots", ()) or ()) + slots
        replacements: dict[str, PreviewMaterialParameterInput] = {}
        overrides = dict(getattr(preview, "preview_native_material_overrides", {}) or {})
        if "base" in added_channels:
            preview.preview_color = (1.0, 1.0, 1.0)
            preview.preview_texture_tint = (1.0, 1.0, 1.0)
            replacements["_baseColorFactor"] = PreviewMaterialParameterInput(
                parameter_kind="color", parameter_name="_baseColorFactor",
                value="#ffffff", color_value=(1.0, 1.0, 1.0),
            )
        for channel, parameter, override in (
            ("roughness", "_roughnessFactor", "roughness"),
            ("metallic", "_metallicFactor", "metalness"),
        ):
            if channel in added_channels:
                overrides[override] = 1.0
                replacements[parameter] = PreviewMaterialParameterInput(
                    parameter_kind="float", parameter_name=parameter,
                    value="1.000000", numeric_value=1.0,
                )
        if not replacements:
            continue
        preview.preview_native_material_overrides = overrides
        parameters = tuple(getattr(preview, "preview_material_parameters", ()) or ())
        preview.preview_material_parameters = tuple(
            parameter for parameter in parameters if parameter.parameter_name not in replacements
        ) + tuple(replacements.values())
        # Texture inputs retain their own parameter copies for material baking.
        preview.preview_material_texture_inputs = tuple(
            replace(texture, material_parameters=tuple(
                replacements.get(parameter.parameter_name, parameter)
                for parameter in texture.material_parameters
            ))
            for texture in tuple(getattr(preview, "preview_material_texture_inputs", ()) or ())
        )
    # Preview recovery must also reach the Builder's source-material inventory.
    scene_result.material_bindings = tuple(
        replace(binding, texture_slots=binding.texture_slots + recovered_slots.get(binding.submesh_index, ()))
        for binding in scene_result.material_bindings
    )
    scene_result.discovered_texture_files = tuple(dict.fromkeys(
        (*scene_result.discovered_texture_files, *(path for slots in recovered_slots.values() for _channel, path in slots))
    ))


@dataclass(frozen=True, slots=True)
class BlenderConversion:
    """What came out of a conversion, for the line the studio logs about it."""

    glb: Path
    blender: Path
    version: str
    objects: int
    vertices: int
    materials: Tuple[str, ...]
    images: Tuple[str, ...]

    def summary(self, source: Path) -> str:
        materials = ", ".join(self.materials) if self.materials else "no materials"
        line = (
            f"{source.name} converted by {self.version or 'Blender'}: {self.vertices:,} vertices in "
            f"{self.objects} object(s), {materials}, {len(self.images)} image(s)."
        )
        if not self.images:
            # said plainly: an FBX that references nothing of its own is common (the magic
            # sword and the Verdict axe are both like it), and what saves those is the
            # studio matching the images lying beside the file by name afterwards
            line += " It references no textures of its own; images beside it are matched by name instead."
        return line


def is_blender_executable(path: object) -> bool:
    """Whether `path` looks like a Blender the studio could run."""

    candidate = Path(str(path or ""))
    if not str(candidate).strip() or not candidate.is_file():
        return False
    stem = candidate.stem.casefold()
    return stem == "blender" or stem.startswith("blender")


def likely_blender_executables() -> Tuple[Path, ...]:
    """Blenders this machine probably has, newest-looking first.

    Only ever a suggestion: a file dialog opens on the first of these so the reader does
    not have to go hunting, and the path that is used is still the one they pick.
    """

    found: list = []

    def offer(path: Path) -> None:
        if is_blender_executable(path) and path not in found:
            found.append(path)

    executable = "blender.exe" if sys.platform.startswith("win") else "blender"
    roots = []
    if sys.platform.startswith("win"):
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            root = os.environ.get(variable)
            if root:
                roots.append(Path(root) / "Blender Foundation")
        roots.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Blender Foundation")
    else:
        roots.extend((Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt")))
    for root in roots:
        try:
            if not root.is_dir():
                continue
            offer(root / executable)
            for child in sorted(root.iterdir(), reverse=True):
                if child.is_dir():
                    offer(child / executable)
                    offer(child / "blender-launcher.exe")
        except OSError:
            continue
    for directory in str(os.environ.get("PATH", "")).split(os.pathsep):
        if directory.strip():
            offer(Path(directory) / executable)
    return tuple(found)


def describe_blender(blender: object) -> str:
    """`blender --version`'s first line, or "" when it will not run."""

    path = Path(str(blender or ""))
    if not is_blender_executable(path):
        return ""
    try:
        finished = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in (finished.stdout or "").splitlines():
        if line.strip().lower().startswith("blender"):
            return line.strip()
    return ""


def convert_fbx_to_glb(
    source: Path,
    blender: object,
    *,
    output_dir: Optional[Path] = None,
    on_log: Optional[Callable[[str], None]] = None,
    timeout_seconds: int = _TIMEOUT_SECONDS,
    run: Optional[Callable[[Sequence[str]], object]] = None,
) -> BlenderConversion:
    """`source` (an `.fbx`) as a GLB written beside it, through `blender`.

    Raises :class:`BlenderNotConfigured` when `blender` is not a Blender, and `RuntimeError`
    when Blender runs but writes nothing -- with what it said on the way out, because "the
    import failed" is not something a reader can act on.
    """

    path = Path(source)
    executable = Path(str(blender or ""))
    if not is_blender_executable(executable):
        raise BlenderNotConfigured(
            "Reading an FBX needs Blender, and the studio has not been pointed at one. "
            "Choose blender.exe on the Model step, or export the model as glTF, GLB, OBJ or DAE yourself."
        )
    if not path.is_file():
        raise RuntimeError(f"{path.name} is not there to convert.")

    target_dir = Path(output_dir) if output_dir is not None else path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{path.stem}.glb"
    with tempfile.TemporaryDirectory(prefix="cdmw_fbx_") as temp:
        script = Path(temp) / "convert.py"
        script.write_text(_SCRIPT, encoding="utf-8")
        command = [
            str(executable), "--background", "--factory-startup",
            "--python-exit-code", "31", "--python", str(script), "--", str(path), str(target),
        ]
        if on_log:
            on_log(f"Converting {path.name} with {executable.name}...")
        if run is not None:
            finished = run(command)
        else:
            try:
                finished = subprocess.run(
                    command, capture_output=True, text=True, timeout=max(10, int(timeout_seconds)),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Blender did not finish converting {path.name} within {timeout_seconds}s.") from exc
            except OSError as exc:
                raise RuntimeError(f"Blender could not be run: {exc}") from exc
        code = int(getattr(finished, "returncode", 1) or 0)
        out = str(getattr(finished, "stdout", "") or "")
        err = str(getattr(finished, "stderr", "") or "")
    if code != 0 or not target.is_file() or target.stat().st_size == 0:
        tail = (err.strip() or out.strip() or "it said nothing").splitlines()
        raise RuntimeError(f"Blender could not convert {path.name} (exit {code}): {tail[-1][:300] if tail else ''}")

    facts = {}
    for line in out.splitlines():
        if line.startswith("CDMW_FBX_RESULT "):
            import json

            try:
                facts = json.loads(line[len("CDMW_FBX_RESULT "):])
            except ValueError:
                facts = {}
    conversion = BlenderConversion(
        glb=target,
        blender=executable,
        version=next((line.strip() for line in out.splitlines() if line.strip().lower().startswith("blender ")), ""),
        objects=int(facts.get("objects", 0) or 0),
        vertices=int(facts.get("vertices", 0) or 0),
        materials=tuple(str(name) for name in (facts.get("materials") or ())),
        images=tuple(str(name) for name in (facts.get("images") or ())),
    )
    if on_log:
        on_log(conversion.summary(path))
    return conversion
