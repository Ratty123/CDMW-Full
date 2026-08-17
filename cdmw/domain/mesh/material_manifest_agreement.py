"""Whether the import's account of a material slot survives to the package.

There are two accounts of one resolution. `ImportedMaterialManifest` answers at
the import transaction, from the routing it performed. The final package
preview's binding rows answer at the export boundary, resolved against the
package and the archive. They agree today because they read the same pipeline,
and nothing has ever checked that.

Collapsing them into one is the finish MESH-007 wants, and it cannot be done
honestly from a desk: the export side resolves against the archive and the
import side does not, so the two can legitimately differ and nobody has measured
by how much. What can be done first is making a disagreement visible, so the
measurement produces a list instead of an argument.

Only what needs no vocabulary mapping is compared. The two sides name semantics
differently -- `base` against `Base / Color` -- and a translation table between
them would be a third thing to keep true. What is compared is presence and
resolution: the import claiming it wrote a file the package has no row for, and
the two disagreeing about whether a target path resolved.
"""

from __future__ import annotations

from dataclasses import dataclass


#: Package-side statuses that mean the binding resolved to a real file. Kept as
#: strings rather than imported from `cdmw.core`, which this layer sits under.
_PACKAGE_RESOLVED_STATUSES = frozenset({"ready"})


@dataclass(frozen=True, slots=True)
class ManifestDisagreement:
    """One target path the two accounts describe differently."""

    target_path: str
    reason: str
    import_side: str
    package_side: str

    def as_line(self) -> str:
        return (
            f"{self.target_path}: {self.reason} "
            f"(import: {self.import_side}; package: {self.package_side})"
        )


def compare_material_manifests(
    imported_manifest: object,
    package_binding_rows: object,
) -> tuple[ManifestDisagreement, ...]:
    """Where the import's account and the package's disagree, by target path.

    Rows the package carries that the import never routed are not reported. The
    package legitimately holds bindings the target already had and the import
    never touched, and calling those disagreements would bury the real signal.
    """

    slots = tuple(getattr(imported_manifest, "slots", ()) or ())
    if not slots:
        return ()

    package_by_path: dict[str, list[object]] = {}
    for row in tuple(package_binding_rows or ()):
        key = _normalized(getattr(row, "texture_path", ""))
        if key:
            package_by_path.setdefault(key, []).append(row)

    disagreements: list[ManifestDisagreement] = []
    for slot in slots:
        target = str(getattr(slot, "target_path", "") or "")
        key = _normalized(target)
        if not key:
            continue
        import_resolved = bool(getattr(slot, "resolved", False))
        rows = package_by_path.get(key, [])
        if not rows:
            if import_resolved:
                # The import believes it produced a file for this slot and the
                # package has no binding at that path at all. Either the routing
                # went somewhere the sidecar does not reference, or the sidecar
                # names a different path than the one that was written.
                disagreements.append(
                    ManifestDisagreement(
                        target_path=target,
                        reason="the import wrote this path but the package has no binding for it",
                        import_side=_status_text(slot),
                        package_side="absent",
                    )
                )
            continue
        package_resolved = any(
            _normalized(getattr(row, "status", "")) in _PACKAGE_RESOLVED_STATUSES for row in rows
        )
        if import_resolved != package_resolved:
            disagreements.append(
                ManifestDisagreement(
                    target_path=target,
                    reason="the two disagree about whether this path resolved",
                    import_side=_status_text(slot),
                    package_side=_normalized(getattr(rows[0], "status", "")) or "unknown",
                )
            )
    return tuple(disagreements)


def manifest_agreement_warnings(
    imported_manifest: object,
    package_binding_rows: object,
    *,
    limit: int = 8,
) -> tuple[str, ...]:
    """Disagreements as reportable lines, headed by how many there are.

    Warnings rather than blockers on purpose. A rule nobody has measured should
    not stop a build the first time it fires; it should say what it saw so the
    rule can be settled.
    """

    disagreements = compare_material_manifests(imported_manifest, package_binding_rows)
    if not disagreements:
        return ()
    lines = [
        f"Imported material manifest disagrees with the packaged bindings in "
        f"{len(disagreements):,} place(s):"
    ]
    lines.extend(f"  {item.as_line()}" for item in disagreements[:limit])
    if len(disagreements) > limit:
        lines.append(f"  ... {len(disagreements) - limit:,} more")
    return tuple(lines)


def _status_text(slot: object) -> str:
    status = getattr(slot, "status", None)
    return str(getattr(status, "value", status) or "unknown")


def _normalized(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


__all__ = [
    "ManifestDisagreement",
    "compare_material_manifests",
    "manifest_agreement_warnings",
]
