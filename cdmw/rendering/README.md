# Rendering

Owns native preview packaging, Rust host integration, material combiner rules,
preview payloads, texture source resolution, capture helpers, and rendering
fidelity checks.

Keep feature UI controls outside this package. UI packages host previews and
display state; rendering code owns resource contracts, material synthesis, and
native preview preparation.

## Shared renderer and package authority

Archive Browser, Model Library, Mesh Editor and Create New Item converge on the
same canonical package and material contracts. A caller may publish bare
geometry while Preview Core prepares canonical textures, but later package
promotion keeps the resident process and camera. `cdmw_mesh_lab` owns the
viewport, HDR studio lighting, and approximate effect-particle drawing; this
package owns the Python-side package, cache, material, and texture inputs rather
than a second renderer. Historical `d3d11_*`, `dotnet_*`, and
`native_preview_*` names are compatibility aliases only.

## Material preparation

PAC detail-layer sampling rules live in `cdmw.domain.material_layer_uv`. The
Python compositor preserves its existing pixel arithmetic, while graph-v5
packages carry the corresponding six-float affine to Rust. Transforms are scoped
to the exact component and material wrapper; old graph-v4 packages retain
identity sampling when the optional field is absent.

Full preview packages bind up to six supported detail layers, including RGB
channels sharing a mask, directly on the GPU. Authored DDS mips stay compressed; dye uses linear
luminance measured from a mip no larger than 64 pixels. The shader applies the
affine, blends normals and reads layer occlusion, roughness and metal directly.
Colour seeds can supply channels without a detail layer. Technical detail masks
use sequential overlays with authored channel flags and opacity, preserving base
colour when only normals are enabled. An absent dye has zero strength; an
explicit white dye remains white. Older packages lacking these sequential controls
keep their CPU route until regenerated. Unsupported graphs or
adapters retain CPU composition, including repeat-wrapped affine sampling.
Grime remains in the conserved graph but is hidden on both preview routes;
`CDMW_PREVIEW_DRAW_GRIME=1` restores it for internal comparisons.

Verified, unchanged source materials in Mesh Editor and Create New Item's
ParsedMesh preview carry the same graph and owned DDS resources as Browse.
Geometry edits retain eligible bindings; imported or changed materials retain
the authoring compositor, painted-channel rules and existing export semantics.
View-only editor references keep their baked materials. Source identity, part
ownership and texture budgets are checked before a graph enters the package.

Fallback texture preparation composes independent materials on up to four CPU workers.
The Rust compositor decodes independent source DDS files on up to four workers,
after the owning reader validates their bytes and admits their decoded sizes
within the existing 512 MiB source-image limit. Workers finish before composition
starts or a failed load returns; shared and directly reusable maps still avoid
duplicate decoding. It shares decoded source pixels, leaves directly usable DDS
maps compressed, and admits composition batches within a shared 512 MiB
working-buffer estimate. Its resident loader keeps at most 128 MiB / 256 entries of completed
material maps; graph settings, presentation and owned texture hashes identify
entries, and every source is still validated on a cache hit. Changing painted
channels invalidates their material. Ordered publication retains texture owners,
full mip chains, authored alpha/response channels and runtime skin detail.

The Mesh Editor's Python material preparation also uses bounded batches. It
keeps repeated materials together for the canonical compiler's existing reuse,
preserves LOD/part ownership, and encodes in source order against one shared
128 MiB fast-preview budget. Cancellation wakes budget waiters and joins the
owned workers before temporary files can be removed. The current scene is
replaced only through the existing completed-package handoff. These changes
affect 3D material preparation. Browse Archives and the Textures replacement
preview use the dedicated GPU DDS viewer; unsupported textures and unavailable
helpers retain the PNG cache. The Texture Editor canvas is unchanged.

Building a preview or Mesh Editor package copies independent geometry batches and
unique texture files on at most four workers per stage, including the first load
after restarting. Results retain source order, hashes and LOD/material ownership.
Texture admission reserves the whole batch's byte and entry limits before workers
start; a source changed after admission cannot exceed its reserved bytes. Failed or
cancelled copies join every worker before the caller removes its temporary output.

## Cache maintenance

Preview cache maintenance never waits on another publisher's build lock. It reads
atomically published metadata, defers busy access timestamps, and skips busy entries
during eviction. Live/recent package leases still protect renderer inputs. This lets
concurrent thumbnail jobs trim the shared cache without deadlocking each other or
blocking cancellation. Clear and prune cover the source, legacy derived, and current
Rust cache tiers; live packages remain protected in each tier. Clear skips busy
publishers and invalidates size accounting so retained packages and failed deletions
still count against the next write's budget.

Archive Browser runs disk clear/prune and PAC index clearing on a tracked background
worker, coalesces queued requests, and reports completion only after the work finishes.
Concurrent scans cannot overwrite newer disk accounting after publication, clear, or
eviction; stale scans use the newer total or retry their snapshot.

## Focused checks

Related tests: native preview, model preview, and static replacement entries under `tests/`.

## Cancelled jobs and resource lifetime

Preview Core removes cancelled protocol job folders after confirming that the helper
stopped. Each new `cdmw_preview_core_*` folder has an ownership marker and a
process-held file lock. Preview preparation sweeps abandoned marked folders older than
thirty minutes. Active jobs, unknown legacy folders, and jobs with unconfirmed helper
termination are preserved. Reference previews release completed native job folders and
their ownership handles as soon as conversion to an independent Rust package finishes or
fails. Other consumers retain their temporary native inputs until they explicitly
release the completed attempt or exit.

Cache-disabled Rust builds remove partial output on errors and cancellation; successful
output remains owned by the receiving caller. Progressive fast-preview packages that
fail or are cancelled before the receiving callback accepts them are also removed. A
completed handoff preserves its files on later cancellation, and durable cache entries
retain their normal cache ownership. Session runtime output is removed only after every
helper using it has stopped, including a retired helper still shutting down after its
replacement starts.

Pending captures report one failure when their renderer fails, their session restarts,
or their helper exits or closes. Late replies cannot publish a failed capture over its
requested output, and internal files remain owned until the writer has finished.

## GPU recovery and reactivation

GPU recovery and hidden-preview reactivation restore live material parameters
along with the scene. Material updates received while hidden are validated and
retained for reactivation. GPU initialization failures report the same paused
renderer state as failed recovery, without automatically relaunching the helper.
Selecting another package keeps it queued and leaves Retry available.
Exhausted surface retries and other terminal render errors use that same paused
state. Occluded surfaces wait for a redraw without entering GPU failure recovery.
Effect-texture aliases share immutable resident bytes by content hash, so the
texture byte budget accounts for their retained data.

## Retained DDS limits

Composed material textures share the 512 MiB retained DDS-payload limit with
authored textures. Publication checks the total after deduplication and before
changing ownership; payloads losing their final owner are released immediately.
Encoding retains its separate per-texture bound. These limits cover texture
payloads, not total process memory or temporary decode/composition buffers.
