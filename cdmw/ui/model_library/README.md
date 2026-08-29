# Model Library

Owns the Model Library tab, audit-result presentation, external model discovery
UI, and model-library preview coordination. Keep slow discovery or preview work
off the UI thread through the tab task worker. Inline preview preparation lives
in `cdmw/services/model_library_preview.py` and is imported inside that task,
not while the tab is constructed. Model Library creates the shared
.NET/Vortice host only when a prepared package is ready, then promotes it after
the host reports `loaded`; the unopened tab retains a lightweight placeholder.
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
