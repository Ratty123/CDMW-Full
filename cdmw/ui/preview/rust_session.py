"""Public Rust Archive Preview session controller.

The implementation remains in the established resident-controller module so
its proven latest-wins, lease, cancellation and shutdown behavior stays intact
during the renderer cutover.
"""

from cdmw.ui.preview.dotnet_session import RustPreviewSessionController

__all__ = ["RustPreviewSessionController"]
