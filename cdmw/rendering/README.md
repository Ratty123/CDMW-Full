# Rendering

Owns native preview packaging, Rust host integration, material combiner rules,
preview payloads, texture source resolution, capture helpers, and rendering
fidelity checks.

Keep feature UI controls outside this package. UI packages host previews and
display state; rendering code owns resource contracts, material synthesis, and
native preview preparation.

Archive Browser, Model Library, Mesh Editor and Create New Item converge on the
same canonical package and material contracts. A caller may publish bare
geometry while Preview Core prepares canonical textures, but later package
promotion keeps the resident process and camera. `cdmw_mesh_lab` owns the
viewport, HDR studio lighting, and approximate effect-particle drawing; this
package owns the Python-side package, cache, material, and texture inputs rather
than a second renderer. Historical `d3d11_*`, `dotnet_*`, and
`native_preview_*` names are compatibility aliases only.

Preview cache maintenance never waits on another publisher's build lock. It
reads atomically published metadata, defers busy access timestamps, and skips
busy entries during eviction. Live/recent package leases still protect renderer
inputs. This lets concurrent thumbnail jobs trim the shared cache without
deadlocking each other or blocking cancellation.
Clear and prune cover the source, legacy derived, and current Rust cache tiers;
live packages remain protected in each tier.

Related tests: native preview, model preview, and static replacement entries under `tests/`.

Preview Core removes cancelled protocol job folders after confirming that the
helper stopped. Each new `cdmw_preview_core_*` folder has an ownership marker
and a process-held file lock. Preview preparation sweeps abandoned marked
folders older than thirty minutes. Active jobs, unknown legacy folders, and
jobs with unconfirmed helper termination are preserved. Reference previews release
completed native job folders and their ownership handles as soon as conversion
to an independent Rust package finishes or fails. Other consumers retain their
temporary native inputs until they explicitly release the completed attempt or
exit. Cache-disabled Rust builds remove partial output on errors and cancellation;
successful output remains owned by the receiving caller. Progressive fast-preview
packages that fail or are cancelled before the receiving callback accepts them
are also removed. A completed handoff preserves its files on later cancellation,
and durable cache entries retain their normal cache ownership. Session runtime
output is removed only after every helper using it has stopped, including a
retired helper still shutting down after its replacement starts.
Pending captures report one failure when their renderer fails, their session
restarts, or their helper exits or closes. Late replies cannot publish a failed
capture over its requested output, and internal files remain owned until the
writer has finished.

GPU recovery and hidden-preview reactivation restore live material parameters
along with the scene. Material updates received while hidden are validated and
retained for reactivation. GPU initialization failures report the same paused
renderer state as failed recovery, without automatically relaunching the helper.
Selecting another package keeps it queued and leaves Retry available.
Exhausted surface retries and other terminal render errors use that same paused
state. Occluded surfaces wait for a redraw without entering GPU failure recovery.
Effect-texture aliases share immutable resident bytes by content hash, so the
texture byte budget accounts for their retained data.

Composed material textures share the 512 MiB retained DDS-payload limit with
authored textures. Publication checks the total after deduplication and before
changing ownership; payloads losing their final owner are released immediately.
Encoding retains its separate per-texture bound. These limits cover texture
payloads, not total process memory or temporary decode/composition buffers.
