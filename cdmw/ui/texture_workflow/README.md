# Textures

Owns the unified **Authoring > Textures** workspace, with one asset list and job.
`TexturesWorkspace` reuses the existing editor for Edit
sessions, layers, and history; Recolor keeps package/ZIP analysis and material-color
rules; Upscale reuses the existing batch pipeline. Replace exposes bulk matching
and mod-package output directly. Review & Export retains native DDS, PNG,
project, recolor, and upscale outputs; its Replacement matches shortcut opens Replace.
Recolor previews use the editor canvas's zoom and original/split views without
changing the document or its undo history. Remove closes the active asset in the
job; it does not delete the source file.
Upscale automatically widens the sidebar when opened or expanded and adjusts it
on window resize while retaining space for the preview. The sidebar follows the
expanded controls' width and selected font size; the Upscale preview can shrink
to leave controls accessible on narrower windows. Asset Authoring path
labels stack above their fields and Browse buttons. The profile and rule tables
open in their own editor through **Workflow Profiles, Rules & Matches > Edit**.
Lazy panels restore their saved settings when first opened.

**Replace** accepts loose PNG/DDS files without opening editor documents or
decoding them for the queue. **Open Folder** recursively replaces the current
shared texture job; **Reload Folder** repeats the last successful folder load,
including external file changes, additions, and deletions. **Add Files** appends
unique paths. Same-name files in different folders remain separate. Empty,
failed, or cancelled scans keep the previous batch. Package settings and earlier
output remain available across reloads.

Queue checkboxes control export inclusion; highlighted rows control **Remove
Selected**. **Clear All** clears the shared job. Bulk removal/reset asks once
before closing existing editor documents, never deletes sources or built packages,
and does not load each intervening document. **Open in Editor** deliberately opens
one asset; returning to Replace preserves its edits, history, and matched original.
Auto-Match remains explicit, and unresolved originals must be chosen before building.
File-only builds read the current source files through the existing package builder;
DDS encoding policy is unchanged. Edited sessions export their current flattened image.

Workers receive immutable snapshots. Revisions, original DDS identity, exact target
matches, and cancellation are checked before accepting results. Batch output is
staged and transactionally published; a failed or cancelled job keeps prior output.
Sources may be loose DDS files, mod folders/ZIPs, or exact archive matches. Extraction
and image processing run off the UI thread and never mutate PAMT/PAZ archives.

`textures` is the canonical navigation key. `texture_editor`, `recolor_variants`,
`texture_workflow`, and `replace_assistant` remain handoff aliases for Edit, Recolor,
Upscale, and Replace. `ui/textures_mode` restores the last mode, falling
back to Edit. Both shell layouts use this same widget and job.
Mode buttons use the shared theme's hover, pressed and selected states. Controls
remain inside their stacked page while loading, so switching modes cannot expose
a second panel over the active one.

Mesh-linked base/albedo documents defer resident dirty-region production until
after the edit handler returns. The producer uses the composite cache, emits a
tight BGRA8 patch, and leases the emitted composite read-only until the Mesh
Editor worker copies it. A racing dirty edit uses copy-on-write, while the
session's original flattened RGBA remains immutable.
