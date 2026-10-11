# Existing texture replacement packages

The v2 .cditem capability and module `texture.replace@1` replace existing shipped
textures through the independent package resolver. They own resource blobs
without an equipment recipe and issue no item, recipe, perk or asset-name IDs.
Package UUIDs, exact content identities, retained reservations and both existing
deployment transactions remain the owners of lifecycle behavior.

## Wire contract

A required module has the existing envelope fields `id`, `type`,
`version`, `required` and `data`. The envelope must require
`"texture.replace": 1`. Its closed data object is:

```json
{
  "registry_sha256": "<SHA-256 of the original PATHC baseline>",
  "replacements": [{
    "path": "character/texture/1_pc/example_d.dds",
    "source_sha256": "<SHA-256 of the complete original DDS>",
    "source_size": 184,
    "replacement": "<content-addressed replacement blob SHA-256>",
    "descriptor_sha256": "<SHA-256 of the original 128- or 148-byte DDS header>"
  }]
}
```

Each target also appears in the envelope's game dependencies with the same source
digest. Target paths must be normalized lower-case game-relative DDS paths.
Each package permits at most 128 targets, counted across modules, with no duplicate
target. All resource blobs must be owned by a supported module. Legacy recipe
blobs retain their existing closed validation; a hybrid may additionally own
texture blobs, including shared content. Logical replacement bytes count for each
target and each selected package even when storage shares one blob. Existing
metadata, resource and aggregate byte limits remain in effect.

## Supported input and source proof

Admission validates the complete DDS payload and mip lengths using the existing
PATHC/DDS owner, then decodes every mip with the packaged Pillow decoder. Resource
limits are checked before decoded allocation. A decoder error is a refusal.
No native build, raw fallback, resampling, codec conversion or guessed color-space
mapping is involved.

The initial adapter supports single-surface 2D block-compressed DDS layouts that
both the existing descriptor reader and that decoder support. Typeless or unknown
formats, arrays, cubes, volumes, truncated payloads and trailing bytes refuse.
The replacement retains the exact complete original DDS header, including reserved
words, caps and every DX10 extension field. This preserves more than the visible
width, height and codec labels.

The target must have a direct entry in the original PATHC registry. The registry
descriptor must agree with the source DDS shape, and the entry's mip storage words
must already match the validated raw mip layout. Collision entries and other
storage layouts remain unsupported. The adapter never adds a registry entry or
rewrites PATHC, shared materials or unrelated metadata.

The package pins the exact original registry baseline. The snapshot separately
retains the hash of the actual registry bytes that were parsed, before any managed
stock-baseline rebase. That source hash, original archive indexes and the source
texture bytes remain guarded through compilation and publication, including
same-size changes that preserve timestamps.

## Composition and lifecycle

Every target contributes a read of its witnessed source and an explicit final
content requirement. Different paths compose. Equal requirements may share output
bytes while retaining both contributors. Different final bytes for the same path
conflict, including an explicit requirement to retain the source bytes.

Legacy recipes' exact borrowed texture requirements remain protected. A mixed
package cannot replace a texture that its own legacy consumer still requires
unchanged. The actual legacy read set distinguishes that case from a disjoint
texture replacement declared in the same envelope.

The existing physical overlay and virtual profile services retain the original
package, recompose remaining owners, verify final output and use their established
history and recovery paths. Semantic exports retain these packages through
`export.semantic@1`; they do not infer texture ownership from byte differences.
Updating a portable file requires the same UUID and expected previous content
digest, stages a package that the actual reader accepts, and validates reviewed
source inputs before the atomic replacement.

Changed shipped inputs retain the existing physical review boundary. Ordinary
removal and stale-package rebuild refuse until that change is reviewed. The
existing explicit retirement route for an unmounted stale set preserves current
stock, identity reservations, retained packages, old archives and recovery
material. Reauthoring then uses the reviewed current source with the same UUID.
Virtual removal recomposes against current shipped inputs. Neither route restores
an obsolete texture backup over a newer original source.

## Evidence boundary

The focused tests use owned synthetic archives and DDS data. They establish the
supported adapter and transaction contract. Visible game behavior remains pending
for an authorized disposable texture trial on each claimed deployment route.
New texture paths, general materials, appearance selectors and other mod
categories require their own verified adapters. Universal mod support remains an
open objective.
