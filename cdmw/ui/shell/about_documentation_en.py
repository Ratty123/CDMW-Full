"""English About documentation content."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Dict, List

from cdmw.domain.textures.plan import describe_processing_path_kind


class AboutDocumentationEnglishMixin:
    """English documentation topic content."""

    def _build_about_sections(self) -> List[Dict[str, str]]:
        readme_path = Path(__file__).resolve().parents[3] / "README.md"
        notices_path = Path(__file__).resolve().parents[3] / "THIRD_PARTY_NOTICES.md"
        license_path = Path(__file__).resolve().parents[3] / "LICENSE"
        readme_text = escape(str(readme_path))
        notices_text = escape(str(notices_path))
        license_text = escape(str(license_path))
        settings_text = escape(str(self.settings_file_path))
        cache_text = escape(str(self.archive_cache_root))
        return [
            {
                "id": "overview",
                "title": "Overview",
                "summary": "High-level tour of the app and its main surfaces.",
                "keywords": "overview about features tabs archive workflow editor replace assistant research text search settings",
                "html": """
                <p>The app is split into major work areas rather than one single pipeline.</p>
                <ul>
                  <li><b>Texture Workflow</b>: batch loose DDS processing, optional upscaling, DDS rebuild, compare, and mod-ready loose export.</li>
                  <li><b>Archive Browser</b>: archive scanning, filtering, preview, extraction, supported patch/loose-export workflows, and Research/Editor handoff.</li>
                  <li><b>Model Library</b>: scan local/importable models, preview them, and route compatible imports into Archive Browser workflows.</li>
                  <li><b>Icon Creator</b>: prepare item-icon source images and package compatible icon replacements.</li>
                  <li><b>Texture Editor</b>: layered visible-texture editing and direct workflow handoff.</li>
                  <li><b>Texture Replacer</b>: guided one-off replacement packaging for edited PNG/DDS files.</li>
                  <li><b>Research</b>: grouped texture families, unknown-resolution work, DDS analysis, references, reports, and notes.</li>
                  <li><b>Text Search</b>: text-like archive/loose-file search with preview and export.</li>
                  <li><b>Profile, Settings, and Window</b>: full app preference export/import, startup/performance/preview controls, language files, and detachable work tabs.</li>
                </ul>
                <p>If you are new to the app, start with <a href="topic:workflow_overview">Texture Workflow</a> and then review <a href="topic:compare_review">Compare &amp; Review</a>.</p>
                """,
            },
            {
                "id": "quick_start",
                "title": "Quick Start",
                "summary": "Fast orientation for choosing the correct first workflow.",
                "keywords": "quick start start here setup first run guide archive texture replace editor research text search",
                "html": """
                <p>Choose the first path based on what you are trying to do. You can move between tools later; the point is to avoid starting with the largest batch workflow when a smaller guided path is safer.</p>
                <ul>
                  <li><b>Browse game files</b>: use <a href="topic:archive_browser">Archive Browser</a> to scan packages, filter, preview, and extract.</li>
                  <li><b>Replace or swap a mesh</b>: use <a href="topic:mesh_media_guides">Mesh Import &amp; Swap</a> from Archive Browser. Start with <b>Import Mesh Preview</b>, then use <b>Import Mesh</b> or <b>Swap With In-Game Mesh</b> after checking alignment.</li>
                  <li><b>Batch-process loose DDS files</b>: use <a href="topic:workflow_overview">Texture Workflow</a>, run a small subset, then review in <a href="topic:compare_review">Compare</a>.</li>
                  <li><b>Replace one already-edited texture</b>: use <a href="topic:replace_assistant">Texture Replacer</a> so the original DDS controls rebuild metadata and output path.</li>
                  <li><b>Edit a visible texture inside the app</b>: use <a href="topic:texture_editor">Texture Editor</a>, then send the flattened PNG onward.</li>
                  <li><b>Understand a texture family</b>: use <a href="topic:research">Research</a> for grouped sets, classification, references, analysis, and notes.</li>
                  <li><b>Find text, XML, JSON, Lua, or config strings</b>: use <a href="topic:text_search">Text Search</a>.</li>
                </ul>
                <p>For a first session, use the bundled <b>cd-texture-dx.exe</b> DDS helper, scan a small source set, avoid technical-map upscaling, and compare output before exporting anything larger.</p>
                """,
            },
            {
                "id": "first_run_checklist",
                "title": "First Run Checklist",
                "summary": "Setup checklist for paths, tools, policy, and first test output.",
                "keywords": "first run checklist setup paths native dds workspace ncnn chainner policy preview compare",
                "html": """
                <ol>
                  <li>Open <b>Settings</b> and run <b>Init Workspace</b> if you want the app to create the usual working folders.</li>
                  <li><b>Native DDS helper</b>: <code>cd-texture-dx.exe</code> is bundled and used automatically for DDS preview, staging, Compare previews, and rebuild.</li>
                  <li>Set <b>Original DDS root</b>, <b>PNG root</b>, and <b>Output root</b>. Use a tiny test folder first.</li>
                  <li>Choose an upscaling backend: <b>Disabled</b> for rebuild testing, direct <b>Real-ESRGAN NCNN</b> for in-app upscale, or <b>chaiNNer</b> for an already-tested chain.</li>
                  <li>Keep a safer <b>Texture Policy</b> preset and automatic rules enabled.</li>
                  <li>Review <b>Workflow Profiles</b>, <b>Ordered Rules</b>, and <b>Matched Files</b> if you need per-file overrides.</li>
                  <li>Click <b>Preview Policy</b> before <b>Start</b> to confirm what the planner will do.</li>
                  <li>Run <b>Scan</b>, process a small batch, then review in <b>Compare</b>.</li>
                  <li>Only after the small batch looks right, expand the folder filter or source root.</li>
                </ol>
                <p>If anything fails, open <a href="topic:troubleshooting">Troubleshooting &amp; Limits</a> and check the Live Log before changing many settings at once.</p>
                """,
            },
            {
                "id": "workflow_overview",
                "title": "Texture Workflow",
                "summary": "Main batch-processing tab for loose DDS files.",
                "keywords": "texture workflow batch dds png rebuild compare start scan preview policy run summary",
                "html": """
                <p><b>Texture Workflow</b> is the main batch-processing tab. It scans loose DDS files under <b>Original DDS root</b>, plans what to do per file, optionally creates/stages PNG intermediates, optionally upscales them, rebuilds DDS output, and lets you review the result in Compare.</p>
                <h4>Typical run</h4>
                <ol>
                  <li>Configure <b>Settings / Setup</b>, <b>Settings / Paths</b>, and <b>DDS Output</b>.</li>
                  <li>Review <a href="topic:workflow_profiles">Workflow Profiles</a>, <a href="topic:workflow_rules">Ordered Rules</a>, and <a href="topic:workflow_matched_files">Matched Files</a>.</li>
                  <li>Choose your backend in <a href="topic:upscaling_backends">Upscaling</a>.</li>
                  <li>Use <b>Preview Policy</b> to inspect the current per-file plan.</li>
                  <li>Run <b>Scan</b> and then <b>Start</b>.</li>
                  <li>Review output in <a href="topic:compare_review">Compare</a>.</li>
                </ol>
                <h4>Main sections inside Texture Workflow</h4>
                <ul>
                  <li><b>Setup</b>: workspace initialization, external tools, help links, and import helpers.</li>
                  <li><b>Paths</b>: source, PNG, staging, output, and optional mod-export roots.</li>
                  <li><b>DDS Output</b>: global default output format/size/mip behavior.</li>
                  <li><b>Workflow Profiles, Rules &amp; Matches</b>: per-file planning surface.</li>
                  <li><b>Upscaling</b>: backend, texture preset, direct NCNN controls, and policy notes.</li>
                  <li><b>Progress / Live Log / Compare</b>: runtime feedback and review.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_profiles",
                "title": "Workflow Profiles",
                "summary": "Reusable named per-file override sets for DDS output and direct NCNN settings.",
                "keywords": "workflow profile selected profile action dds format size mips ncnn scale tile post correction",
                "html": """
                <p><b>Workflow Profiles</b> are reusable named override sets. They are assigned by ordered rules and only override the fields you fill in. Blank fields inherit the current global workflow settings.</p>
                <h4>Selected Profile fields</h4>
                <ul>
                  <li><b>Name</b>: display name used in the rules table and matched-files table.</li>
                  <li><b>Action</b>: force one action mode for matching files. <code>Inherit Planner</code> lets the planner decide; <code>Upscale Then Rebuild</code>, <code>Rebuild From PNG</code>, <code>Preserve Original</code>, and <code>Skip</code> force that result.</li>
                  <li><b>DDS Format / DDS Size / Mipmaps</b>: optional DDS output overrides applied after the file is matched.</li>
                  <li><b>Direct NCNN Model / Scale / Tile / Extra Args / Post Correction</b>: optional per-file direct-NCNN overrides. These matter only when the selected backend is direct <b>Real-ESRGAN NCNN</b>.</li>
                </ul>
                <h4>Starter profiles</h4>
                <ul>
                  <li><b>Starter Color / Albedo</b>: batch-upscale baseline for visible color-style textures.</li>
                  <li><b>Starter Normal</b>: preserve-first baseline for normal maps.</li>
                  <li><b>Starter Height / Displacement</b>: preserve-first baseline for scalar height/displacement maps.</li>
                  <li><b>Starter Specular</b>: preserve-first baseline for specular-like scalar masks.</li>
                </ul>
                <p>The starters are meant to be sane defaults, not universal â€œbestâ€ answers. If a file family really should be pushed through rebuild or direct NCNN, duplicate the starter and make a more aggressive variant.</p>
                """,
            },
            {
                "id": "workflow_rules",
                "title": "Ordered Rules",
                "summary": "Last-match-wins assignment table that maps files to workflow behavior.",
                "keywords": "ordered rules selected rule match glob exact path workflow profile semantic planner profile colorspace alpha planner path last match wins",
                "html": """
                <p><b>Ordered Rules</b> are evaluated from top to bottom with <b>last match wins</b>. Exact-path rules and glob rules share one list.</p>
                <h4>Selected Rule fields</h4>
                <ul>
                  <li><b>Enabled</b>: disabled rules stay in the list but are ignored.</li>
                  <li><b>Match</b>: <code>Glob</code> matches basename or relative path patterns; <code>Exact Path</code> targets one exact relative path.</li>
                  <li><b>Pattern</b>: the glob or exact relative path to match.</li>
                  <li><b>Workflow Profile</b>: assigns one of the reusable workflow profiles above.</li>
                  <li><b>Semantic</b>: optional manual semantic override such as <code>normal:normal</code> or <code>height:displacement</code>.</li>
                  <li><b>Planner Profile</b>: optional processing-profile override that changes planner assumptions such as preferred compression, colorspace, and preserve behavior. See <a href="topic:workflow_planner_profiles">Planner Profiles</a>.</li>
                  <li><b>Colorspace</b>: optional rule-level colorspace override.</li>
                  <li><b>Alpha Policy</b>: optional rule-level alpha handling override.</li>
                  <li><b>Planner Path</b>: optional path override that tells the planner which intermediate route to prefer. See <a href="topic:workflow_planner_paths">Planner Paths</a>.</li>
                </ul>
                <h4>Authoring notes</h4>
                <ul>
                  <li>Put broad family rules near the top and one-off exact-path fixes near the bottom.</li>
                  <li>Use the <a href="topic:workflow_matched_files">Matched Files</a> table when you want to turn selected rows into exact-path assignment rules quickly.</li>
                  <li>If you are unsure, inspect the result in <b>Preview Policy</b> before running <b>Start</b>.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_planner_profiles",
                "title": "Planner Profiles",
                "summary": "Meaning of planner-profile values under Selected Rule.",
                "keywords": "planner profiles selected rule color_default normal_bc5 scalar_bc4 scalar_high_precision_bc4 packed mask premultiplied float vector",
                "html": """
                <p><b>Planner Profile</b> is a low-level processing profile used by the planner. It influences preferred texture format, colorspace, alpha policy, mip hint, allowed path kinds, and preserve-first behavior.</p>
                <ul>
                  <li><code>color_default</code>: visible color textures. Prefers sRGB-aware color handling and color-style mip treatment.</li>
                  <li><code>color_cutout_alpha</code>: visible textures with cutout alpha where alpha coverage should be preserved more carefully.</li>
                  <li><code>ui_alpha</code>: UI-style visible textures with alpha.</li>
                  <li><code>normal_bc5</code>: normal maps. Linear, BC5-oriented, preserve-first.</li>
                  <li><code>scalar_bc4</code>: generic single-channel scalar/mask data. Linear, BC4-oriented, preserve-first.</li>
                  <li><code>scalar_high_precision_bc4</code>: eligible scalar technical maps that may use the high-precision technical path instead of the generic visible PNG path.</li>
                  <li><code>packed_mask_preserve_layout</code>: packed-channel masks and response maps. Preserve-first to avoid channel drift.</li>
                  <li><code>premultiplied_alpha_review_required</code>: premultiplied-alpha content that should be reviewed manually.</li>
                  <li><code>float_or_vector_preserve_only</code>: float, vector, or other precision-sensitive technical data that should stay preserve-only.</li>
                </ul>
                <p>In practice, use workflow profiles for the user-facing batch behavior and use planner profiles only when you specifically need to change the plannerâ€™s technical assumptions for a matched file or file family.</p>
                """,
            },
            {
                "id": "workflow_planner_paths",
                "title": "Planner Paths",
                "summary": "Meaning of planner-path values under Selected Rule.",
                "keywords": "planner paths selected rule visible_color_png_path technical_preserve_path technical_high_precision_path",
                "html": f"""
                <p><b>Planner Path</b> chooses the intermediate route the planner should prefer for a matched file.</p>
                <ul>
                  <li><code>visible_color_png_path</code>: {escape(describe_processing_path_kind("visible_color_png_path"))}</li>
                  <li><code>technical_preserve_path</code>: {escape(describe_processing_path_kind("technical_preserve_path"))}</li>
                  <li><code>technical_high_precision_path</code>: {escape(describe_processing_path_kind("technical_high_precision_path"))}</li>
                </ul>
                <h4>Backend behavior</h4>
                <ul>
                  <li><b>Disabled backend</b>: visible-color path rebuilds from current PNG inputs. The high-precision path can rebuild from valid high-bit-depth PNG data if present.</li>
                  <li><b>Direct Real-ESRGAN NCNN</b>: visible-color path is supported. Technical high-precision path is not supported in the current tranche, so preserve behavior wins when that path is chosen.</li>
                  <li><b>chaiNNer</b>: only the visible-color path is trusted in the current tranche. Technical preserve/high-precision paths stay preserve-first.</li>
                </ul>
                <p>Use planner-path overrides carefully. Forcing technical textures onto <code>visible_color_png_path</code> is intentionally treated as a higher-risk choice.</p>
                """,
            },
            {
                "id": "workflow_matched_files",
                "title": "Matched Files",
                "summary": "Live current-match view for the workflow file set.",
                "keywords": "matched files assign profile exact path rules action effective dds ncnn summary current filter",
                "html": """
                <p><b>Matched Files</b> is a live table for the current workflow match set: DDS files under <b>Original DDS root</b> that also match the current folder/file filter.</p>
                <h4>Columns</h4>
                <ul>
                  <li><b>Path</b>: relative path inside the current Original DDS root.</li>
                  <li><b>Semantic</b>: current inferred or overridden semantic type/subtype.</li>
                  <li><b>Rule</b>: the last matching ordered rule.</li>
                  <li><b>Workflow</b>: the assigned workflow profile, if any.</li>
                  <li><b>DDS Output</b>: effective DDS output override summary.</li>
                  <li><b>NCNN</b>: effective direct-NCNN summary for that file.</li>
                  <li><b>Action</b>: final planned action after planner, rule, profile, backend, and safety logic are combined.</li>
                </ul>
                <p><b>Assign Profile</b> creates new exact-path rules for the selected rows. Because ordered rules are last-match-wins, these one-off assignment rules are appended at the end of the current rule list.</p>
                """,
            },
            {
                "id": "dds_output",
                "title": "DDS Output & Staging",
                "summary": "Global DDS rebuild defaults used by the workflow.",
                "keywords": "dds output format size mipmaps staging native png size match original custom",
                "html": """
                <p><b>DDS Output</b> defines the global rebuild defaults for files that do not receive a workflow-profile override.</p>
                <ul>
                  <li><b>Format</b>: match the original DDS or force one supported native DDS format.</li>
                  <li><b>Size</b>: rebuild to PNG size, original DDS size, or a custom size.</li>
                  <li><b>Mipmaps</b>: keep original count, generate a full chain, use a single mip, or force a custom count.</li>
                  <li><b>DDS staging</b>: when enabled with an upscaling backend, the app first converts matched DDS files to a staging PNG root before the backend runs.</li>
                </ul>
                <p>Workflow profiles can override these per file. That is why DDS Output should be thought of as the global default layer, not always the final result.</p>
                """,
            },
            {
                "id": "upscaling_backends",
                "title": "Upscaling & Backends",
                "summary": "How disabled mode, direct NCNN, and chaiNNer behave.",
                "keywords": "upscaling backend ncnn chainner disabled scale tile retry post correction source match direct backend",
                "html": """
                <p>The app supports three high-level modes in <b>Upscaling</b>.</p>
                <ul>
                  <li><b>Disabled</b>: no upscale backend. The workflow can still rebuild DDS from existing PNG inputs.</li>
                  <li><b>Real-ESRGAN NCNN</b>: direct in-app backend with global model, scale, tile, extra args, retry/fallback behavior, and optional post correction.</li>
                  <li><b>chaiNNer</b>: external chain-based backend. The chain remains the source of truth for what actually happens.</li>
                </ul>
                <h4>Important notes</h4>
                <ul>
                  <li>Per-file direct-NCNN overrides only apply when the selected backend is direct <b>Real-ESRGAN NCNN</b>.</li>
                  <li>Automatic texture rules and planner behavior still matter even when an upscale backend is enabled.</li>
                  <li><b>Run Summary</b> is the read-only preflight view for current sources, backend, texture preset, and export behavior.</li>
                  <li><b>Preview Policy</b> is the per-file plan view for the current workflow match set.</li>
                </ul>
                """,
            },
            {
                "id": "texture_workflow_guides",
                "title": "Texture Workflow Guides",
                "summary": "Recipes for common DDS rebuild, upscale, and profile tasks.",
                "keywords": "texture workflow guides recipe rebuild upscale ncnn chainner dds staging profile exact path rules",
                "html": """
                <h4>Rebuild DDS without upscaling</h4>
                <ol>
                  <li>Set <b>Original DDS root</b>, <b>PNG root</b>, and <b>Output root</b>. The bundled native DDS helper is selected automatically.</li>
                  <li>Set backend to <b>Disabled</b>.</li>
                  <li>Place edited PNG files under <b>PNG root</b> using matching relative paths.</li>
                  <li>Use <b>Scan</b>, then <b>Preview Policy</b>, then <b>Start</b>.</li>
                </ol>
                <h4>Direct NCNN upscale test</h4>
                <ol>
                  <li>Configure the NCNN executable and model folder.</li>
                  <li>Start with color/UI/emissive content only, or assign exact-path rules for the files you want to test.</li>
                  <li>Use a modest tile value if VRAM is limited. If the backend fails, lower tile size before changing models.</li>
                  <li>Review in Compare and only then expand the filter.</li>
                </ol>
                <h4>Use profiles for a mixed folder</h4>
                <ol>
                  <li>Create or duplicate workflow profiles for visible color, preserve-only technical maps, and any special DDS output needs.</li>
                  <li>Add broad glob rules for common suffix families near the top.</li>
                  <li>Use <b>Matched Files</b> to create exact-path rules for exceptions near the bottom.</li>
                  <li>Open <b>Preview Policy</b> and confirm the final action column before running.</li>
                </ol>
                """,
            },
            {
                "id": "compare_review",
                "title": "Compare & Review",
                "summary": "Side-by-side original/output DDS review.",
                "keywords": "compare review side by side sync pan preview size mip details open in texture editor",
                "html": """
                <p><b>Compare</b> is the final review surface for the current loose output set.</p>
                <ul>
                  <li>Preview original DDS and output DDS side by side.</li>
                  <li>Change fit/zoom level, pan each side, or enable <b>Sync Pan</b>.</li>
                  <li>Open the current texture in <b>Texture Editor</b> or jump to mip details in Research.</li>
                  <li>Use this before large runs or before packaging output for a mod-ready folder.</li>
                </ul>
                """,
            },
            {
                "id": "archive_browser",
                "title": "Archive Browser",
                "summary": "Archive scan, preview, item lookup, active mod/original state, extraction, and supported patch surface.",
                "keywords": "archive browser pamt paz scan preview filter extract patch mod ready mesh audio video text dds workflow research texture editor item finder dmm active mod shadowed placement hkx",
                "html": """
                <p><b>Archive Browser</b> is the in-app inspection surface for Crimson Desert package data. It can browse archives in flat or tree view, preview many supported formats directly, extract files, and for supported workflows either patch the game archives or write mod-ready loose output with confirmation and backup support.</p>
                <div class="doc-callout doc-warning"><b>First scan note:</b> set <b>Settings &gt; Archive Locations &gt; Game / Package</b> first. Optional global sidecar indexing can take a long time because it reads many material sidecars to build reverse texture connections. If you enable it, let it complete; worker count and cache behavior are configured in <b>Settings &gt; Archive Browser Performance</b>.</div>
                <table>
                  <tr><th>Area</th><th>What it is for</th><th>Typical actions</th></tr>
                  <tr><td>Archive Files</td><td>Browsable index of package entries.</td><td>Filter, sort columns, resize columns, switch Flat/Folders/Categories, select files or folders, and read the <b>State</b> column for active mod/original/shadowed duplicate status.</td></tr>
                  <tr><td>Preview</td><td>Fast look at the selected asset.</td><td>View images, color-coded text/XML/HKX summaries, binary summaries, audio/video, 3D models, and sidecar-derived material context.</td></tr>
                  <tr><td>Referenced Files</td><td>Connection map for the selected asset.</td><td>Find textures, material sidecars, skeletons, animations, metadata, packages, resolution status, and usage counts.</td></tr>
                  <tr><td>Details</td><td>Structured metadata and diagnostics.</td><td>Check sizes, compression, package labels, strings, import summaries, preview diagnostics, and warnings.</td></tr>
                  <tr><td>Item Finder</td><td>Visual item lookup backed by iteminfo, localization, icons, and archive relationships.</td><td>Search by item name/category, browse icons, jump back to archive entries, and choose a placement source from resolved item assets.</td></tr>
                  <tr><td>Mesh Actions</td><td>Model export/import, placement, and replacement workflow entry points.</td><td>Export OBJ/FBX, import OBJ/DAE/glTF/GLB preview, import DDS preview, import mesh replacement, swap with another in-game mesh, edit HKX placement context, Weapon Placement Batch, restore backups, edit material values.</td></tr>
                  <tr><td>HKX / Placement</td><td>Socket, prefab, and placement-copy workflows for weapons and other attachment-driven assets.</td><td>Edit HKX placement context from HKX/model selections, choose a .pac placement source, use Item Finder, compare source/target placement, edit socket values, and build one loose placement-copy package.</td></tr>
                </table>
                <ul>
                  <li>Scan package roots and cache the discovered archive index locally.</li>
                  <li>Filter by path, package, folder, likely role, size, and previewability, then switch between flat and tree browsing as needed.</li>
                  <li>Use the <b>State</b> column to understand duplicates from mod managers such as DMM: active mod rows override originals, shadowed rows are present but not the active payload, and mod-added rows have no original counterpart.</li>
                  <li>Preview supported DDS/images, text-like files, structured assets such as <code>.app_xml</code>, <code>.prefabdata_xml</code>, <code>.prefab</code>, <code>.levelinfo</code>, <code>.palevel</code>, <code>.roadsector</code>, <code>.road</code>, <code>.nav</code>, <code>.pabc</code>, <code>.pabv</code>, <code>.pabgb</code>, <code>.pabgh</code>, HKX/Havok summaries, audio/video, and model assets such as <code>.pam</code>, <code>.pamlod</code>, and <code>.pac</code>.</li>
                  <li>Extract selected or filtered content to loose folders.</li>
                  <li>Use <b>Item Finder</b> when a name/category/icon is a better starting point than a raw path; armor and horse gear categories are inferred from item names, IDs, and game metadata where possible.</li>
                  <li>Inspect referenced model textures, export supported meshes as OBJ/FBX, import OBJ/DAE/glTF/GLB for rebuilt preview, swap one archive mesh with another in-game mesh, and choose between archive patching or mod-ready loose export for supported mesh flows.</li>
                  <li>Use <b>Edit HKX</b> and <b>Choose Placement Source</b> for socket/prefab-driven placement swaps. Pick the visible source <code>.pac</code> when possible; the picker uses a static geometry thumbnail so browsing candidates does not depend on a nested live model view.</li>
                  <li>Replace supported archive DDS entries from DDS or PNG, patch supported audio entries, and restore backups created by supported patch operations.</li>
                  <li>Send DDS content into Texture Workflow, open supported images in Texture Editor, or resolve items in Research.</li>
                </ul>
                <p>Not every archive format is editable. Browsing and preview support is broader than patch support, so use the visible actions beside the preview to see what is currently available for the selected entry.</p>
                """,
            },
            {
                "id": "archive_guides",
                "title": "Archive Browser Guides",
                "summary": "Simple archive scanning, filtering, extracting, and handoff recipes.",
                "keywords": "archive guide scan cache filter tree flat extract referenced files handoff research editor workflow",
                "html": """
                <h4>Scan packages</h4>
                <ol>
                  <li>Set the package root in <b>Settings &gt; Archive Locations</b>. This should be the Crimson Desert folder or package root that contains the game archive files.</li>
                  <li>Click <b>Scan</b>. Use the cached result on repeat scans when the package files have not changed.</li>
                  <li>Use flat view when searching broadly and tree view when following folders.</li>
                </ol>
                <div class="doc-callout"><b>Finding things quickly:</b> the main search checks paths, basenames, and linked item/localization aliases when the item-name index is available. <b>Exact Item Name</b> is only filled when the package data provides a direct iteminfo/localization-to-model hash link. <b>Related Name Hint</b> is broader navigation evidence; it is not proof that the selected file is that item.</div>
                <h4>Find useful files</h4>
                <ul>
                  <li>Filter by path fragments, package, file extension, role, size, and previewability.</li>
                  <li>Use inclusion filters for what you want and exclusion filters for noisy families.</li>
                  <li>For meshes and sidecars, review <b>Referenced Files</b> to find related textures, XML, material sidecars, skeletons, and metadata.</li>
                  <li>Use <b>Item Finder</b> for name/icon/category-based lookup when the archive path is unknown.</li>
                </ul>
                <table>
                  <tr><th>Goal</th><th>Use</th><th>Notes</th></tr>
                  <tr><td>Find a character or item model</td><td>Search by file stem, folder, or in-game name; use <b>Exact Item Name</b> and <b>Related Name Hint</b> columns when available.</td><td>Exact names require direct package links. Related hints are useful for navigation but are not proof of item identity.</td></tr>
                  <tr><td>Tell which duplicate is active</td><td>Read the <b>State</b> column.</td><td><b>Active mod</b> is the replacement payload currently winning over an original; <b>Shadowed original</b> or <b>Shadowed mod</b> means another row with the same virtual path has priority.</td></tr>
                  <tr><td>Find textures used by a model</td><td>Select the model and read <b>Referenced Files</b>.</td><td>Resolved means the app found an archive entry; partial means metadata exists but some texture decoding or archive data is incomplete.</td></tr>
                  <tr><td>Choose a placement source</td><td>Use <b>Edit HKX</b>, then <b>Choose Placement Source</b>, or pick through <b>Item Finder</b>.</td><td>Choose the visible source <code>.pac</code> when possible. HKX is useful context, but placement usually resolves through prefab/socket data around the model family.</td></tr>
                  <tr><td>Find material values</td><td>Look for <code>.pac_xml</code>, <code>.pam_xml</code>, <code>.pamlod_xml</code>, or <code>.pami</code> sidecars.</td><td>Use <b>Edit Material Values</b> for source-ordered guided controls. A <code>.pac_xml</code> opens the PAC XML Editor with Parameters, Connections, and Source &amp; Changes tabs.</td></tr>
                  <tr><td>Understand a selected file</td><td>Open <b>Details</b>.</td><td>Details includes package, raw/stored size, compression, preview diagnostics, readable strings, and import summaries.</td></tr>
                </table>
                <h4>Modded duplicates and active rows</h4>
                <ul>
                  <li>When original and modded packages contain the same virtual path, the browser keeps both rows visible so you can inspect exactly what exists.</li>
                  <li><b>Active mod</b> and <b>Active original</b> mark the row that currently wins for that virtual path. <b>Shadowed</b> rows are lower priority. <b>Mod-added</b> means the file exists only in a mod package.</li>
                  <li>Use this before extracting or replacing files so you know whether you are looking at original game data or a DMM/mod-manager replacement.</li>
                </ul>
                <h4>Extract or hand off</h4>
                <ul>
                  <li><b>Export Selected</b> is the safest path for a small number of files.</li>
                  <li><b>Export All</b> or filtered extraction is useful after you verify the filter matches exactly what you expect.</li>
                  <li>Send supported DDS/images to <b>Texture Workflow</b>, <b>Texture Editor</b>, or <b>Research</b> when you want deeper processing.</li>
                </ul>
                <p>Archive patching is intentionally separate from normal browsing. Patch actions only appear for supported formats and use explicit confirmation plus backup/restore where available.</p>
                """,
            },
            {
                "id": "mesh_media_guides",
                "title": "Mesh, Audio & Media Guides",
                "summary": "How to approach model previews, mesh export/import, audio, video, and sidecar files.",
                "keywords": "mesh media model preview pam pamlod pac obj fbx gltf dae audio wem bnk video bk2 sidecar",
                "html": """
                <h4>Model preview</h4>
                <ul>
                  <li>Open supported <code>.pam</code>, <code>.pamlod</code>, and <code>.pac</code> entries in Archive Browser to inspect geometry, bounds, materials, sidecars, and referenced textures.</li>
                  <li>Use <b>Preview Settings</b> when textures, support maps, lighting, or orientation need adjustment for inspection.</li>
                  <li>Referenced files are discovery aids. Export them with the model when you need context for external tools.</li>
                </ul>
                <h4>Mesh export and import</h4>
                <ul>
                  <li><b>OBJ export</b> is the round-trip baseline when the app can write sidecar data needed for import preview.</li>
                  <li><b>FBX export</b> is useful for external inspection, but not every FBX edit can be round-tripped into game data.</li>
                  <li><b>GLB/glTF/DAE imports</b> are treated as static replacement sources where supported; skins, bones, animations, and complex material graphs are not converted into native game material data.</li>
                </ul>
                <table>
                  <tr><th>Action</th><th>Use it when</th><th>Result</th></tr>
                  <tr><td>Export OBJ</td><td>You want an editable round-trip source with companion metadata.</td><td>Writes mesh data and sidecar/context files where supported.</td></tr>
                  <tr><td>Export FBX</td><td>You want inspection or DCC convenience.</td><td>Good for viewing; not a guarantee of patchable import.</td></tr>
                  <tr><td>Import Mesh Preview</td><td>You want to test an OBJ/DAE/glTF/GLB replacement without writing output.</td><td>Builds a preview only.</td></tr>
                  <tr><td>Import DDS Preview</td><td>You want to test a DDS texture override on the selected model without writing output.</td><td>Builds a model preview only.</td></tr>
                  <tr><td>Import Mesh</td><td>You are ready to export a supported replacement.</td><td>Lets you choose archive patching or mod-ready loose output where supported.</td></tr>
                  <tr><td>Swap With In-Game Mesh</td><td>You want another loaded archive mesh to replace the selected target mesh.</td><td>Sets a target, then uses the chosen source mesh in Mesh Replacement Alignment with related files carried over where supported.</td></tr>
                  <tr><td>Edit HKX</td><td>You opened an HKX/model and need to copy placement from another weapon/model family.</td><td>Shows target context, lets you choose a placement source, compares source/target placement, and builds a loose placement-copy package.</td></tr>
                  <tr><td>Edit Material Values</td><td>The selected mesh has a recognized XML/material sidecar.</td><td>Opens an isolated, screen-aware editor that can be maximized. Parameters provides typed controls and undo/reset; Parameters and Connections column headings sort on click and reverse on a second click; Connections navigates current-index and Asset Family evidence without scanning or changing the browser selection; Source &amp; Changes shows read-only, line-numbered XML with syntax colors and red/green unified diffs. For PAC XML, the approximate model preview omits skeleton/HKX overlay data by default; enable Show skeleton overlay only when rig context is useful. Export writes a mod-ready package while preserving the source encoding and untouched XML bytes.</td></tr>
                </table>
                <h4>Mesh Replacement Alignment</h4>
                <ul>
                  <li>The alignment dialog is the review gate for static mesh replacements and in-game mesh swaps. Use it to inspect geometry, mapped parts, texture slot mapping, sidecar choices, placement, scale, rotation, and export values.</li>
                  <li><b>Live Alignment Preview</b> is the transform workspace. The <b>Original Reference</b> shows the donor/target placement, and <b>Replacement Preview</b> is the replacement at the actual candidate offset, rotation, and scale that will be written if you continue. This is especially useful for hand-held weapons, props, and other assets where the origin must line up with a grip, socket, or original reference point.</li>
                  <li>The live preview is intentionally fast and optimistic: it uses the current mapping, transform, and selected texture slots before packaging. After loose export, the Archive Preview switches to a final-output view when possible, using packaged sidecar/DDS paths. If that view looks worse, the issue is usually final material/texture binding rather than placement.</li>
                  <li><b>Import Mesh Preview</b> opens this flow without writing files. Use it first when testing OBJ, DAE, glTF, GLB, or an in-game source mesh.</li>
                  <li><b>Import Mesh</b> writes only after the same checks. Depending on the target and compatibility review, output can be mod-ready loose files or a confirmed archive patch.</li>
                  <li>Texture slot plans and original DDS overrides are advanced repair tools. Prefer suggested mappings first, then manually override only the slots you understand.</li>
                </ul>
                <h4>Material Authority and sidecars</h4>
                <ul>
                  <li><b>Runtime XML preserve</b> keeps target/corpus PAC XML structure when you need the safest material-sidecar baseline.</li>
                  <li><b>True Source Authority</b> uses original PAC/XML as runtime ABI while allowing source-owned texture/material authority where compatible.</li>
                  <li><b>Material Authority</b> uses the proven source-owned route: source color through overlay color, source PBR/material mask through detail mask, and no glossy color-blend response.</li>
                  <li><b>Material Authority Manual</b> starts from Runtime XML preserve and exposes override knobs for advanced repair.</li>
                  <li>Legacy Runtime XML and True Source profiles stay loadable for old settings/debug, but are no longer shown as default choices.</li>
                  <li><b>Use Another Original Mesh</b> lets you pick a different original reference when the selected target is not the best authority for alignment/material context.</li>
                  <li>Placement state matters for items with body and hand variants: review <b>Stowed / on body</b> versus <b>Held / in hand</b> before building a package.</li>
                </ul>
                <h4>In-game mesh swap</h4>
                <ol>
                  <li>Select the archive mesh you want to replace and click <b>Swap With In-Game Mesh</b> or use the context menu to start the swap target.</li>
                  <li>Choose what related files may be included, such as textures, material sidecars, appearance descriptors, prefabdata, skeletons, or animations. Use <b>Character Swap Plan</b> for experimental full-character/body swaps; it selects the discovered appearance graph and enables source <code>.app_xml</code> replacement. Material sidecars control shader/texture bindings; appearance descriptors can redirect character prefabs, customization metadata, scale values, skeleton variations, sockets, and prefabdata references. Skeleton and animation replacement is intentionally explicit because incompatible rigs or physics data can break assets.</li>
                  <li>Select another loaded archive mesh as the source and use it as the swap source.</li>
                  <li>Review placement and texture mapping in <b>Mesh Replacement Alignment</b>.</li>
                  <li>Use preview first. Only write loose output or patch archives after the result is visually and structurally plausible.</li>
                </ol>
                <div class="doc-callout doc-warning"><b>Mesh limits:</b> static replacement can retarget geometry and compatible material sidecars, but it does not convert every external rig, animation, character appearance graph, skin, or complex DCC material graph into native game data. Full character/body swaps often require matching <code>.app_xml</code>, <code>.prefabdata_xml</code>, skeleton variation, physics, socket, customization, and texture references.</div>
                <h4>HKX placement and socket workflows</h4>
                <ul>
                  <li><b>Edit HKX</b> treats the opened asset as the target that changes. <b>Choose Placement Source</b> finds the source weapon/model whose placement should be copied.</li>
                  <li>Pick a visible source <code>.pac</code> when possible. The picker can search the archive indexes directly or use <b>Pick From Item Finder</b> to start from item name/icon/category.</li>
                  <li>The placement source picker uses a static geometry thumbnail for source candidates. This keeps browsing stable while still confirming that the selected source is the expected model.</li>
                  <li><b>Compare Placement</b> verifies the resolved prefab/socket/HKX context before packaging. <b>Edit Socket Values</b> is available when the recovered socket XML can be safely shown and written as loose output.</li>
                </ul>
                <h4>Audio, video, and text-like media</h4>
                <ul>
                  <li>Preview supported audio/video where the local system codecs allow it.</li>
                  <li>Use soundbank summaries to inspect <code>.bnk</code> structure.</li>
                  <li>Use Text Search or Archive Preview for text-like formats before extracting large groups.</li>
                </ul>
                """,
            },
            {
                "id": "texture_editor",
                "title": "Texture Editor",
                "summary": "Layered editor for visible-texture work.",
                "keywords": "texture editor layers masks selections brush clone heal smudge patch gradient dodge burn channels compare",
                "html": """
                <p><b>Texture Editor</b> is built for visible-color texture work rather than general-purpose technical-map authoring.</p>
                <ul>
                  <li>Layered document with paint, erase, fill, gradient, clone, heal, smudge, patch, dodge/burn, sharpen, and soften tools.</li>
                  <li>Selections, floating paste/move workflow, masks, channel locks, and non-destructive adjustments.</li>
                  <li>RGBA/original/split preview modes and direct handoff to Compare, Texture Replacer, and Texture Workflow.</li>
                  <li>Warnings are shown for technical textures because the editor is not the safest place to rebuild those blindly.</li>
                </ul>
                """,
            },
            {
                "id": "replace_assistant",
                "title": "Texture Replacer",
                "summary": "Guided one-off replacement flow for edited PNG/DDS files.",
                "keywords": "replace assistant replace edited png dds original match mod ready loose export package",
                "html": """
                <p><b>Texture Replacer</b> is the best route when you already have an edited PNG or DDS and want to match it back to the correct original texture, rebuild it safely, and export a ready loose mod folder.</p>
                <ul>
                  <li>Match edited assets to original DDS files or archive entries.</li>
                  <li>Apply correction and rebuild logic with current output settings.</li>
                  <li>Export a mod-ready loose folder structure for the matched results.</li>
                </ul>
                """,
            },
            {
                "id": "research",
                "title": "Research",
                "summary": "Texture-family inspection, unknown-resolution, DDS QA, reports, and notes.",
                "keywords": "research unknown resolver grouped families dds qa reports heatmaps notes references",
                "html": """
                <p><b>Research</b> is the analysis surface for grouped texture families and metadata-heavy review.</p>
                <ul>
                  <li>Inspect grouped DDS families and their inferred semantic roles.</li>
                  <li>Use <b>Unknown Resolver</b> to review and assign uncertain classifications.</li>
                  <li>Open DDS analysis, reports, references, and local notes.</li>
                  <li>Review planner/path/profile summaries and family-level context before committing to risky workflow overrides.</li>
                </ul>
                """,
            },
            {
                "id": "text_search",
                "title": "Text Search",
                "summary": "Search archive and loose text-like files with preview and export.",
                "keywords": "text search xml json cfg lua regex export preview encrypted xml archive loose",
                "html": """
                <p><b>Text Search</b> is for archive or loose-file search across text-like assets such as <code>.xml</code>, <code>.json</code>, <code>.cfg</code>, <code>.lua</code>, and similar formats.</p>
                <ul>
                  <li>Search with preview and syntax-colored match context.</li>
                  <li>Work against archive data or loose folders.</li>
                  <li>Export matched results while preserving folder structure.</li>
                </ul>
                """,
            },
            {
                "id": "mod_packaging",
                "title": "Mod Packaging & Output",
                "summary": "How loose output, mod-ready folders, metadata, and backups fit together.",
                "keywords": "mod packaging output loose mod ready info json no_encrypt package prefix backup restore export",
                "html": """
                <p>The app keeps normal workflow output and mod-ready packaging separate so you can review results before placing them into a mod manager.</p>
                <ul>
                  <li><b>Output root</b> is the normal DDS result folder for Texture Workflow.</li>
                  <li><b>Mod-ready export</b> writes a package-prefixed loose tree with <code>manifest.json</code> and optional manager metadata when that export mode is enabled.</li>
                  <li><b>Target Mod Managers</b> can write DMM, CDUMM, JMM JSON, Crimson Sharp / Crimson Browser, and Field-JSON v3.1 shapes. CDUMM uses <code>manifest.json</code>, <code>modinfo.json</code>, <code>.no_encrypt</code>, and a <code>files/</code> wrapper; DMM texture folders use <code>modinfo.json</code>, while DMM mesh folders keep <code>manifest.json</code> plus <code>modinfo.json</code>.</li>
                  <li><b>Texture Replacer</b> is usually the cleanest path for one-off mod-ready texture output because it starts from the edited file and its matched original.</li>
                  <li><b>Archive Browser</b> patch workflows are explicit, confirmed operations with backup/restore support where implemented. They are not part of ordinary browsing.</li>
                </ul>
                <p>Recommended practice: build into a review folder, inspect in Compare or an external viewer, then copy or point your mod manager at the final mod-ready folder.</p>
                """,
            },
            {
                "id": "profile_settings",
                "title": "Profile & Settings",
                "summary": "What app profiles, settings pages, diagnostics, and language files include.",
                "keywords": "profile settings export import diagnostics language appearance startup performance preview texture editor replacer",
                "html": """
                <p><b>Profile &gt; Export Profile</b> writes both the workflow configuration and a full settings snapshot. Current profiles include paths, workflow rules/profiles, mod-package metadata, current Archive Browser controls, appearance, language, startup restore, performance, archive cache/indexing preferences, 3D preview graphics controls, Texture Replacer options, Texture Editor brush/tool preferences, safety prompts, and saved window geometry.</p>
                <ul>
                  <li>An app profile is one app-wide snapshot, not a separate profile per tab. It includes per-tool preferences and detached window layout inside that one profile file.</li>
                  <li><b>Import Profile</b> restores the workflow config first, then reloads the saved app settings into the live Settings, Texture Replacer, and Texture Editor controls.</li>
                  <li>Profiles do not save open archives, active documents, or per-tab project sessions.</li>
                  <li><b>Export Diagnostics</b> includes the same profile payload plus logs, cache summaries, chain analysis, crash context when available, a paste-ready issue summary, README, license, and third-party notices. Reports stay local until you export and share them.</li>
                  <li><b>Settings / Startup</b> controls archive auto-load, cache preference, and last-tab restore. Archive filters start neutral after launch.</li>
                  <li><b>Settings / Performance</b> controls workload presets, archive-list batching/native helper use, optional DDS related-file indexing, preview caches, and D3D11 preview package caching.</li>
                  <li><b>Settings / Appearance</b> controls themes, built-in Spanish/German/custom language files, fonts, density, log colors, preview colors, and 3D graphics defaults.</li>
                  <li><b>Settings / Layout and Safety</b> control pane-size memory, cleanup confirmations, and extra local diagnostic context.</li>
                </ul>
                <p>Language export writes a JSON file with English keys and translated values. Keep keys unchanged, edit only values, then import the file from Settings / Appearance.</p>
                """,
            },
            {
                "id": "window_layout",
                "title": "Window & Layout",
                "summary": "Detachable work tabs, saved geometry, and layout memory.",
                "keywords": "window layout detach attach tab geometry splitter restore detached tool",
                "html": """
                <p>The <b>Window</b> menu lets heavy work areas run in their own top-level windows while keeping their original navigation slots available.</p>
                <ul>
                  <li><b>Detach Current Tool</b> moves the current detachable tool into a separate window and leaves a placeholder behind.</li>
                  <li><b>Reattach Current Tool</b> and <b>Reattach All Tools</b> return detached tools to their original tab groups.</li>
                  <li>Detached windows remember their geometry under <code>window/detached/&lt;tool&gt;/geometry</code>. The main window stores <code>window/geometry</code>.</li>
                  <li><b>Settings / Layout</b> controls whether pane sizes and splitters are remembered across sessions.</li>
                  <li>Archive Browser, Texture Workflow, Texture Editor, Model Library, Icon Creator, Research, and Text Search can be restored from their placeholders or the Window menu.</li>
                </ul>
                """,
            },
            {
                "id": "safety",
                "title": "Safety Model",
                "summary": "Preserve-first defaults, technical texture risk, confirmations, and recoverability.",
                "keywords": "safety preserve technical texture normal mask packed vector height displacement backup confirmation dry run cache",
                "html": """
                <p>The app is conservative because many DDS files are data textures, not ordinary pictures. A texture that looks dull, flat, noisy, or channel-packed may be carrying normals, masks, vectors, height, or material response data.</p>
                <ul>
                  <li><b>Texture Policy</b> and automatic rules try to keep risky technical maps away from generic visible PNG/upscale processing.</li>
                  <li><b>Planner profiles</b> and <b>planner paths</b> are advanced controls for changing those assumptions when you know the file family.</li>
                  <li><b>Preview Policy</b> is the per-file preflight view. Use it before large runs.</li>
                  <li><b>Dry run</b> and small folder filters are useful for validating a plan without committing to a full output pass.</li>
                  <li>Archive patching requires explicit action and uses backups where supported; extraction and preview are read-only.</li>
                </ul>
                <p>If you are not sure what a file is, classify or inspect it in Research before assigning an aggressive workflow profile.</p>
                """,
            },
            {
                "id": "settings_files",
                "title": "Settings, Files & Dependencies",
                "summary": "Local config, cache, project files, and external dependencies.",
                "keywords": "settings files config cache dependency native dds ncnn chainner license readme notices",
                "html": f"""
                <p>The app stores its local settings and archive cache beside the executable or local source checkout.</p>
                <ul>
                  <li><b>Config file</b>: <code>{settings_text}</code></li>
                  <li><b>Archive cache</b>: <code>{cache_text}</code></li>
                  <li><b>README</b>: <code>{readme_text}</code></li>
                  <li><b>License</b>: <code>{license_text}</code></li>
                  <li><b>Third-party notices</b>: <code>{notices_text}</code></li>
                </ul>
                <h4>External requirements</h4>
                <ul>
                  <li><b>cd-texture-dx.exe</b> is bundled and required for DDS preview, DDS-to-PNG conversion, compare preview, and DDS rebuild.</li>
                  <li><b>Real-ESRGAN NCNN</b> and <b>chaiNNer</b> are optional backends.</li>
                </ul>
                <h4>References</h4>
                <ul>
                  <li><a href="https://github.com/microsoft/DirectXTex">Microsoft DirectXTex project</a></li>
                  <li><a href="https://chainner.app/download/">chaiNNer download page</a></li>
                  <li><a href="https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan">Real-ESRGAN NCNN Vulkan</a></li>
                  <li><a href="https://www.nexusmods.com/crimsondesert/mods/62">Crimson Desert Unpacker</a></li>
                  <li><a href="https://www.nexusmods.com/crimsondesert/mods/84">Crimson Browser &amp; Mod Manager</a></li>
                </ul>
                """,
            },
            {
                "id": "faq",
                "title": "FAQ",
                "summary": "Short answers to common setup, workflow, and output questions.",
                "keywords": "faq questions answers native dds ncnn chainner replace assistant texture workflow archive patch settings cache brightness technical maps",
                "html": """
                <p><b>Do I need to install a DDS converter?</b><br/>No. CDMW bundles <b>cd-texture-dx.exe</b> and uses it for all DDS preview and rebuild workflows.</p>
                <p><b>Should I upscale every texture?</b><br/>No. Start with visible color, UI, or emissive textures. Normals, packed masks, vectors, height maps, and displacement maps should usually stay preserve-first unless you know the family.</p>
                <p><b>When should I use Texture Replacer?</b><br/>Use it for one-off edited PNG/DDS replacements. Use Texture Workflow for batch rebuild or batch upscale of a loose DDS tree.</p>
                <p><b>What is the safest first backend?</b><br/>Use <b>Disabled</b> first to prove paths and DDS rebuild behavior. Then test direct <b>Real-ESRGAN NCNN</b> or a known-good <b>chaiNNer</b> chain on a small subset.</p>
                <p><b>Why did output brightness or detail change?</b><br/>Upscale models and correction modes can shift luma, contrast, alpha, or detail. Compare against the original, test a different model, reduce aggressive settings, or try Source Match correction for visible textures.</p>
                <p><b>Can the app patch archives directly?</b><br/>Only for supported workflows. Ordinary browsing, preview, and extraction are read-only; patch actions require explicit confirmation and use backup/restore support where implemented.</p>
                <p><b>Where are settings stored?</b><br/>The config file and cache are stored beside the executable or local source checkout. See <a href="topic:settings_files">Settings, Files &amp; Dependencies</a>.</p>
                <p><b>Why does search not find my topic?</b><br/>Try feature names, tab names, file types, field labels, or symptoms such as <code>native DDS</code>, <code>brightness</code>, <code>normal</code>, <code>archive</code>, <code>profile</code>, or <code>mod-ready</code>.</p>
                """,
            },
            {
                "id": "troubleshooting",
                "title": "Troubleshooting & Limits",
                "summary": "Common failure cases and current limitations.",
                "keywords": "troubleshooting limits native dds ncnn chainner png output brightness drift preview archive cache",
                "html": """
                <ul>
                  <li><b>Missing native DDS helper</b>: DDS preview and rebuild stop with an explicit native-backend error. Check that <code>cd-texture-dx.exe</code> was packaged beside the app.</li>
                  <li><b>Missing NCNN models</b>: direct NCNN requires a valid executable and matching <code>.param</code> / <code>.bin</code> models.</li>
                  <li><b>No matching PNG outputs</b>: if the selected backend produces no usable PNG output, DDS rebuild has nothing to convert.</li>
                  <li><b>Wrong chaiNNer paths</b>: hardcoded chain paths can make the chain read from or write to the wrong directory.</li>
                  <li><b>Brightness or detail drift</b>: compare outputs carefully, test another model, or change direct-NCNN post correction.</li>
                  <li><b>Archive preview limits</b>: unusual DDS layouts and very large archive scans are still best-effort cases.</li>
                  <li><b>Technical textures</b>: preserve-first handling is still the safer default for normals, masks, packed channels, vectors, and other precision-sensitive maps.</li>
                </ul>
                """,
            },
        ]
