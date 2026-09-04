# Model Library

Owns the Model Library tab, audit-result presentation, external model discovery
UI, and model-library preview coordination. Keep slow discovery or preview work
off the UI thread through the tab task worker. Inline preview preparation lives
in `cdmw/services/model_library_preview.py` and is imported inside that task,
not while the tab is constructed. Model Library creates the shared
Rust host only when a prepared package is ready, then promotes it after the
host reports `ready`; the unopened tab retains a lightweight placeholder.
Archive Browser preview remains an explicit manual action.

Scene imports (glTF/GLB/OBJ/DAE) normalize texture V, so the preparation step
stamps that orientation onto the preview meshes before the canonical package is
written; the Flip V control inverts the same value and rebuilds. Prepared
packages are cached by an identity covering source and referenced-resource
content/revisions, selected ZIP member, render settings, orientation,
cache/compiler profile and app version. A valid hit is accepted before scene
import and returns its stored geometry/texture summary with the package, so
re-selecting a model or toggling Flip V back skips parsing and packaging. An
unsupported or incomplete dependency shape bypasses durable reuse rather than
risking stale rendering.

Pre-decoded external geometry is labelled `preview` inside the Rust document;
the manifest separately retains its true glTF, GLB, OBJ, DAE, or converted-FBX
source format. External images are deduplicated by source and texture role, then
encoded through one native DDS batch per package while preserving the existing
format, mip, memory-budget, cancellation, and atomic-publication contracts.
Non-PNG images (including JPEG, TGA, and WebP) are normalized to temporary RGBA
PNGs for the PNG-only native encoder; those intermediates are removed after
success, failure, or cancellation.
Their temporary preview copies are aspect-preservingly bounded to 2048 pixels;
the downloaded source images remain unchanged.

Inline packages use the shared Rust direct-texture tier: authored DDS resources
remain visible, while full PAC/PAC_XML material synthesis stays reserved for
surfaces that promote to the complete tier. Direct packages have their own
durable cache identity and cannot be mistaken for a full-material package.

ZIP discovery/extraction and generic Preview/Import path resolution run through
the Model Library task worker. Results are discarded when the selected row
changes. The shell imports scene geometry and scans texture/sidecar companions
in its cancellable utility worker before opening import setup; an archive
selection change invalidates the prepared result.

Immutable catalogue records, extension/status fields, URL normalization, and
download-candidate policy live in `cdmw/domain/library/models.py`. Scan,
catalogue, download, and extraction I/O is coordinated by `ModelLibraryService`.

Local scan normalization, bounded metadata reads, file/status probes, mirror
download-state filtering, column filtering, and sorting produce one immutable
prepared-row result in that same tracked task lane. The UI only rejects stale
request IDs and adds already-prepared rows in batches.

Compact Workspace rearranges these same widgets without creating a second
Model Library implementation. Its controls lane is bounded to 256-300 px and
does not horizontally scroll at the supported compact sizes, even after another
tool changes the process-wide UI font; the compact content ignores its former
wide minimum-size hint and wraps into the bounded viewport. Results keep the
remaining width, while details sit beside the resident preview. Classic Workspace
retains the original arrangement.

Confirmed local deletion also uses the tracked task lane. The worker revalidates
the approved root and downloaded-folder ownership marker, plans recursively
with cooperative cancellation before mutation, then removes the confirmed
targets. Shutdown cancels and drains the owning task thread.

Generated preview icons capture only a detached framebuffer image on the UI
thread. Scaling, PNG encoding, collision-safe naming, and atomic publication run
in the same cancellable task lane; stale selections and shutdown suppress output
delivery and remove unpublished temporary files.
