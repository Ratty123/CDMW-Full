# Textures

Owns the unified **Authoring > Textures** workspace, with one asset list and job.
`TexturesWorkspace` reuses the existing editor for Edit
sessions, layers, and history; Recolor keeps package/ZIP analysis and material-color
rules; Upscale reuses the existing batch pipeline. Review & Export owns replacement
matching and the existing native DDS, PNG, project, and mod-package outputs.
Recolor previews use the editor canvas's zoom and original/split views without
changing the document or its undo history. Remove closes the active asset in the
job; it does not delete the source file.
Upscale controls fit the sidebar; the profile and rule tables open in their own
editor through **Workflow Profiles, Rules & Matches > Edit**. Lazy panels restore
their saved settings when first opened.

Workers receive immutable snapshots. Revisions, original DDS identity, exact target
matches, and cancellation are checked before accepting results. Batch output is
staged and transactionally published; a failed or cancelled job keeps prior output.
Sources may be loose DDS files, mod folders/ZIPs, or exact archive matches. Extraction
and image processing run off the UI thread and never mutate PAMT/PAZ archives.

`textures` is the canonical navigation key. `texture_editor`, `recolor_variants`,
`texture_workflow`, and `replace_assistant` remain handoff aliases for Edit, Recolor,
Upscale, and replacement review. `ui/textures_mode` restores the last mode, falling
back to Edit. Both shell layouts use this same widget and job.

Mesh-linked base/albedo documents defer resident dirty-region production until
after the edit handler returns. The producer uses the composite cache, emits a
tight BGRA8 patch, and leases the emitted composite read-only until the Mesh
Editor worker copies it. A racing dirty edit uses copy-on-write, while the
session's original flattened RGBA remains immutable.
