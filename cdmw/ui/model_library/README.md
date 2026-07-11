# Model Library

Owns the Model Library tab, audit-result presentation, external model discovery
UI, and model-library preview coordination. Keep slow discovery or preview work
off the UI thread through the tab task worker. Inline preview preparation lives
in `cdmw/services/model_library_preview.py`. Model Library auto-preview and
Preview Here use the inline native D3D11 host by default so loaded models draw
in the preview pane. The first native inline load uses fast preview textures and
promotes the D3D11 widget only after the host reports `loaded`. Archive Browser
preview remains an explicit manual action.

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

Confirmed local deletion also uses the tracked task lane. The worker revalidates
the approved root and downloaded-folder ownership marker, plans recursively
with cooperative cancellation before mutation, then removes the confirmed
targets. Shutdown cancels and drains the owning task thread.

Generated preview icons capture only a detached framebuffer image on the UI
thread. Scaling, PNG encoding, collision-safe naming, and atomic publication run
in the same cancellable task lane; stale selections and shutdown suppress output
delivery and remove unpublished temporary files.
