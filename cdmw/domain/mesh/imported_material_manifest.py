"""What an import resolved, per material slot, owned by the import itself.

The import transaction already knew all of this. It just never said so in a form
anything could read: the account of which source file reached which target slot
was a run of log lines assembled at the end of
`append_texture_replacement_report`, truncated at sixteen rows, with no status
and no structure. Asking "which texture maps will this build actually write" had
no answer short of reading the build log and trusting it.

`TextureResolutionManifest` in `cdmw/core/final_package_preview.py` answers the
same question, but only once the final package preview has been built -- which is
after the decision the reader wanted it for. This is the earlier half: the same
question answered by the transaction that resolved it.

Deliberately a description. It computes no routing and converts no texture; it
reports what the pipeline already decided, so the two cannot disagree about what
was written.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath


class MaterialSlotStatus(str, Enum):
    #: A new texture was produced for this slot and is in the package.
    GENERATED = "generated"
    #: The source file is packaged as-is, without conversion.
    COPIED = "copied"
    #: Routed to an output path that nothing in the package satisfies.
    MISSING = "missing"


#: Slot kinds a build cannot be complete without. Everything else is optional in
#: the sense the plan means: absent, the game falls back rather than draws wrong.
REQUIRED_SLOT_SEMANTICS = frozenset({"base", "color", "basecolor", "base_color", "diffuse"})


@dataclass(frozen=True, slots=True)
class ImportedMaterialSlot:
    """One routed slot: where it came from, what it became, where it went."""

    target_material: str
    target_path: str
    semantic: str
    source_material: str
    source_path: str
    conversion: str
    status: MaterialSlotStatus

    @property
    def is_required(self) -> bool:
        return _normalized_semantic(self.semantic) in REQUIRED_SLOT_SEMANTICS

    @property
    def resolved(self) -> bool:
        return self.status is not MaterialSlotStatus.MISSING

    def as_payload(self) -> dict[str, object]:
        return {
            "target_material": self.target_material,
            "target_path": self.target_path,
            "semantic": self.semantic,
            "source_material": self.source_material,
            "source_path": self.source_path,
            "conversion": self.conversion,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class ImportedMaterialManifest:
    """Every slot the import routed, with the warnings and errors it raised."""

    schema: str = "cdmw_imported_material_manifest_v1"
    slots: tuple[ImportedMaterialSlot, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def counts_by_semantic(self) -> dict[str, int]:
        return dict(Counter(_normalized_semantic(slot.semantic) for slot in self.slots))

    def missing_slots(self) -> tuple[ImportedMaterialSlot, ...]:
        return tuple(slot for slot in self.slots if not slot.resolved)

    def missing_required_slots(self) -> tuple[ImportedMaterialSlot, ...]:
        return tuple(slot for slot in self.missing_slots() if slot.is_required)

    def summary_lines(self) -> tuple[str, ...]:
        """The pre-commit Textures block, read off the manifest rather than retold.

        The build log used to assemble this itself from the same rows. Rendering
        it here is what keeps the log and the manifest from disagreeing about
        what a build wrote.
        """

        if not self.slots:
            return ()
        counts = self.counts_by_semantic()
        by_semantic = ", ".join(f"{name}: {count:,}" for name, count in sorted(counts.items()))
        missing = self.missing_slots()
        lines = [
            f"Imported material slots resolved: {len(self.slots):,} ({by_semantic})",
        ]
        if missing:
            lines.append(f"Imported material slots with no packaged file: {len(missing):,}")
        required_missing = self.missing_required_slots()
        if required_missing:
            lines.append(
                "Missing required texture(s): "
                + ", ".join(sorted({slot.target_path for slot in required_missing}))
            )
        return tuple(lines)

    def as_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "slots": [slot.as_payload() for slot in self.slots],
            "counts_by_semantic": self.counts_by_semantic(),
            "missing": len(self.missing_slots()),
            "missing_required": len(self.missing_required_slots()),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def build_imported_material_manifest(
    report: object,
    *,
    packaged_target_paths: object = (),
) -> ImportedMaterialManifest:
    """Read a texture replacement report into a manifest.

    Duck-typed on purpose: the report is a `cdmw.modding` type and this module
    is pure domain, so it reads the fields rather than importing the class.

    `packaged_target_paths` is what the build is actually going to write. A slot
    routed to a path nothing writes is the case the plan calls a binding with no
    file behind it, and it is the only way to tell `generated` from `missing`
    without guessing.
    """

    packaged = {_normalized_path(path) for path in tuple(packaged_target_paths or ())}
    packaged.discard("")
    slots: list[ImportedMaterialSlot] = []
    for mapping in tuple(getattr(report, "slot_mappings", ()) or ()):
        output_path = str(getattr(mapping, "output_texture_path", "") or "")
        source_path = str(getattr(mapping, "source_path", "") or "")
        slots.append(
            ImportedMaterialSlot(
                target_material=str(getattr(mapping, "target_material_name", "") or ""),
                target_path=output_path or str(getattr(mapping, "target_texture_path", "") or ""),
                semantic=str(getattr(mapping, "slot_kind", "") or ""),
                source_material=str(getattr(mapping, "source_material_name", "") or ""),
                source_path=source_path,
                conversion=_conversion_label(source_path, output_path, getattr(mapping, "normal_space", "")),
                status=_slot_status(output_path, source_path, packaged),
            )
        )
    return ImportedMaterialManifest(
        slots=tuple(slots),
        warnings=tuple(str(line) for line in tuple(getattr(report, "warnings", ()) or ())),
        errors=tuple(str(line) for line in tuple(getattr(report, "errors", ()) or ())),
    )


def _slot_status(
    output_path: str,
    source_path: str,
    packaged: set[str],
) -> MaterialSlotStatus:
    if not output_path:
        return MaterialSlotStatus.MISSING
    if _normalized_path(output_path) in packaged:
        return MaterialSlotStatus.GENERATED
    # No packaged payload claims this path. A source file still on disk means
    # the pipeline intends to copy it; nothing at all means the slot is routed
    # to a file that will not exist.
    return MaterialSlotStatus.COPIED if source_path else MaterialSlotStatus.MISSING


def _conversion_label(source_path: str, output_path: str, normal_space: object) -> str:
    """What happened to the bytes between source and target, in one token."""

    source_suffix = PurePosixPath(str(source_path or "").replace("\\", "/")).suffix.lower().lstrip(".")
    target_suffix = PurePosixPath(str(output_path or "").replace("\\", "/")).suffix.lower().lstrip(".")
    space = str(normal_space or "").strip().lower()
    if not source_suffix or not target_suffix:
        parts = []
    elif source_suffix == target_suffix:
        parts = ["none"]
    else:
        parts = [f"{source_suffix}->{target_suffix}"]
    if space:
        parts.append(f"normal_space={space}")
    return " ".join(parts) if parts else "unknown"


def _normalized_semantic(value: object) -> str:
    return str(value or "").strip().lower() or "unknown"


def _normalized_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


__all__ = [
    "REQUIRED_SLOT_SEMANTICS",
    "ImportedMaterialManifest",
    "ImportedMaterialSlot",
    "MaterialSlotStatus",
    "build_imported_material_manifest",
]
