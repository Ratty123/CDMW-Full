using System.Globalization;
using System.IO;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private UiLocalizationOwner? _uiLocalizationOwner;

    private void HandleUiLocalizationState(JsonElement root)
    {
        var acknowledgement = new Dictionary<string, object?>
        {
            ["language_code"] = JsonString(root, "language_code"), ["plural_rule"] = JsonString(root, "plural_rule"),
            ["catalog_hash"] = JsonString(root, "catalog_hash"), ["key_manifest_hash"] = JsonString(root, "key_manifest_hash"),
            ["session_id"] = JsonString(root, "session_id"), ["process_generation"] = JsonLongValue(root, "process_generation"),
            ["request_id"] = JsonLongValue(root, "request_id"), ["localization_revision"] = JsonLongValue(root, "localization_revision"),
        };

        _uiLocalizationOwner ??= new UiLocalizationOwner(this, _helpToolTip);
        if (_uiLocalizationOwner.TryApply(root, out var status, out var reason))
        {
            acknowledgement["status"] = status;
        }
        else
        {
            acknowledgement["status"] = status;
            acknowledgement["reason"] = reason;
        }
        StartupTiming.Mark("ui_localization_state_applied");
        WriteProtocolEvent("ui_localization_state_ack", acknowledgement);
    }
}

internal sealed partial class UiLocalizationOwner : IDisposable
{
    public const int MaximumProtocolLineBytes = 256 * 1024;

    private static readonly string[] KeyManifest =
    {
    // BEGIN GENERATED UI LOCALIZATION KEYS
        "(Win32 {value_0}). The rail stays on the previous tool.",
        "+{value_0}",
        "-{value_0}",
        "1. Set Selected Driver Parts",
        "2. Bind Selected Garment Parts",
        "A part cannot be both driver and garment: {value_0}.",
        "Action History",
        "Active procedural values are non-destructive. Bake or Reset before topology edits.",
        "Acts on the viewport mesh selection or the explicit PARTS selection. ",
        "Add",
        "Adjust profile sliders, optionally bind garment parts, then review and Bake. Slider changes remain non-destructive until baked.",
        "Adjust the active topology-bound values.",
        "Advanced ▸",
        "Advanced ▾",
        "All",
        "Alt + left-drag",
        "Alt + left-drag, or middle / right-drag",
        "Alt + left-drag, or middle-drag",
        "Alt + left-drag, or right-drag",
        "Alt or Ctrl + left-drag",
        "Alt or Ctrl + left-drag, or middle / right-drag",
        "Alt or Ctrl + left-drag, or middle-drag",
        "Alt or Ctrl + left-drag, or right-drag",
        "Amount at 100%",
        "Apply Enabled, mode, intensity, and clearance to the selected bound garment parts as one undoable edit.",
        "Apply or save a named set of slider values.",
        "Apply to Selected Garments",
        "Applying the latest Morph & Refit value...",
        "Axis",
        "Back",
        "Background",
        "Bake",
        "Bake or Reset active procedural sliders before changing topology.",
        "Base mesh is always included. Only the active layer can be edited; visible inactive layers are reference geometry.",
        "Base mesh is always visible.",
        "Bottom",
        "Brush",
        "Brush Tools",
        "Brush falloff preview",
        "Brushes paint the replacement under the yellow circle; no preselection is required. Left-drag to apply. Right-drag pans; wheel zooms.",
        "CDMW .NET Mesh Editor Experiment",
        "COMMANDS",
        "Camera: {value_0}.",
        "Cancel",
        "Captured mesh selection: {value_0} vertices, {value_1} edges, {value_2} faces.",
        "Category",
        "Choose Glow Colour",
        "Choose Part Colour",
        "Choose Part Tint",
        "Choose a profile above, or Create Profile... to build another one from selected parts.",
        "Choose at least one part or open the wizard with a viewport mesh selection.",
        "Choose the preview mode, topology appearance, viewport background, or a camera preset. Mouse and keyboard bindings update with the active tool.",
        "Choose whole parts",
        "Clear Refit",
        "Clear Selection",
        "Clearance (% driver size)",
        "Click or drag on the mesh to select vertices, wires, or faces. Brush, Rectangle and Lasso never select PARTS; X-Ray selects through the mesh.",
        "Colour",
        "Command result: {value_0}.",
        "Command result: {value_0}. Restored last acknowledged state.",
        "Command result: {value_0}. {value_1}",
        "Committed selection color",
        "Committing visible Morph & Refit state before Finish Edit Mesh...",
        "Comparison",
        "Constant",
        "Copy",
        "Create Morph Profile",
        "Create Profile...",
        "Create or choose a profile, adjust its sliders, optionally bind a garment, then review and Bake. Saving a profile never bakes the mesh.",
        "Create or choose a topology-matched profile and its sliders.",
        "Ctrl + left-drag",
        "Ctrl + left-drag, or middle / right-drag",
        "Ctrl + left-drag, or middle-drag",
        "Ctrl + left-drag, or right-drag",
        "D3D11/Vortice HLSL material viewport initialized.",
        "D3D11/Vortice material viewport unavailable; {value_0}: {value_1}",
        "Default percent",
        "Default percent must be inside the selected range.",
        "Definition profiles, shape sliders and garment refit binding.",
        "Deformation",
        "Delete",
        "Delete Preset",
        "Delete Profile",
        "Delete Selection",
        "Discard all live slider values.",
        "DotNetMeshEditorPartColourStatus",
        "DotNetMeshEditorPartEmissiveCheck",
        "DotNetMeshEditorPartRecolourStrengthValue",
        "Down",
        "Driver: not set",
        "Driver: {value_0}",
        "Duplicate",
        "Duplicate Selection",
        "Edge mode: selected={value_0} hover={value_1} xray={value_2}",
        "Edit Morph Profile Slider",
        "Edit...",
        "EditMeshSessionTitle",
        "Embedded .NET mesh editor ready.",
        "Emits light",
        "Enter a profile name.",
        "Enter a slider label.",
        "Every applied mesh edit and selection change appears here. Undone actions remain visible for Redo.",
        "FPS -- | Frame -- ms",
        "FPS {value_0} | Interval {value_1} ms | P95 {value_2} ms",
        "FPS: {value_0} | Interval: {value_1} ms | P95: {value_2} ms | Render: {value_3} ms | Present: {value_4} ms | Backend: {value_5}",
        "Faces",
        "Faces (No Textures)",
        "Faces + Wire",
        "Falloff",
        "Feather rings",
        "Finish Edit Mesh",
        "Finish the current Morph profile preview or save before opening another wizard.",
        "First set selected driver parts, then select and bind garment parts.",
        "Fit",
        "Flatten",
        "Focus Imported / Modify",
        "Focus Original",
        "Focus the Imported / Modify pane's independent camera. Both side-by-side panes remain visible.",
        "Focus the Original pane's independent camera. Both side-by-side panes remain visible.",
        "Follow intensity (%)",
        "Front",
        "Garment: not bound",
        "Garment: {value_0} | {value_1} vertices | max {value_2} | p95 {value_3}",
        "General",
        "Glow...",
        "Grab",
        "Grab radius",
        "Grid",
        "Grow",
        "Hidden",
        "Hide",
        "Ignored stale Morph & Refit change.",
        "Ignored stale Morph & Refit state.",
        "Ignored stale or uncorrelated command result.",
        "Ignored stale or uncorrelated selection update.",
        "Imported / Modify (focus)",
        "Inflate",
        "Invert",
        "Lasso",
        "Layer name cannot be empty.",
        "Layers",
        "Left",
        "Linear",
        "Live",
        "Live MeshService bridge connected.",
        "Live selection color",
        "Loaded package. materials={value_0} textureRefs={value_1} resolved={value_2}/{value_3} decodable={value_4}/{value_5}. Solid view is on; wire overlay is optional.",
        "Loading textures before the resident editor becomes ready...",
        "Loading textures in the resident viewport...",
        "Make the selected parts the driver body that bound garments follow.",
        "Material",
        "Maximum percent",
        "Mesh Edit Session",
        "Mesh Edit Session, Editable view",
        "Mesh geometry layers",
        "Mesh vertex selection: drag shape, combine mode and X-Ray.",
        "Minimum percent",
        "Minimum percent must be lower than maximum percent.",
        "Mirror",
        "Morph & Refit",
        "Morph & Refit is ready.",
        "Morph profile command sequence stopped after a rejected step.",
        "Move",
        "Move drags the current selection freely in screen space; Grab pulls vertices under the brush. ",
        "Move requires a selection. Use Select in the viewport or choose a part under PARTS.",
        "Move the selected faces into a part of their own, so colour applies to just them.",
        "Move the selection one step along +{value_0}.",
        "Move the selection one step along -{value_0}.",
        "My Morph Profile",
        "My Preset",
        "New Slider",
        "Next",
        "No acknowledged viewport mesh selection was available when the wizard opened.",
        "No edit actions yet",
        "No profile yet. Select one or more parts, then Create Profile... to build the first slider. Saving it does not Bake the mesh.",
        "None",
        "Off",
        "Optional Refit",
        "Orbit",
        "Original (focus)",
        "Original pane focused. Both previews remain visible; its camera is independent.",
        "Overlay",
        "Pan",
        "Part Pick",
        "Part Pick disabled; clearing selection.",
        "Part Pick enabled; selection requests target source parts.",
        "Part selection awaiting authoritative acceptance.",
        "Parts",
        "Paste",
        "Pinch",
        "Placement",
        "Placement gizmo: {value_0}. Left-drag the viewport or use the Builder placement values.",
        "Placement mode: enable Edit Mesh to mutate geometry.",
        "Preview ",
        "Preview mode",
        "Preview mode: {value_0}.",
        "Preview part pick: no hit.",
        "Preview part pick: {value_0}",
        "Profile",
        "Profile ID",
        "Profile ID cannot be empty.",
        "Profile Values",
        "Profile name",
        "Profile: {value_0}\nSelection: {value_1}\nSlider: {value_2} — {value_3}{value_4}\nRange: {value_5}% to {value_6}% (default {value_7}%)",
        "Push penetration outward to this percentage of the driver's bounding-box diagonal after refit.",
        "Queued {value_0} until the active Morph change finishes.",
        "Radius",
        "Recolour...",
        "Recolours the selected parts. Tint multiplies the existing texture, so it can only ",
        "Rectangle",
        "Redo",
        "Refine Smooth",
        "Refit enabled for selected garments",
        "Refit mode",
        "Refit settings only apply to bound garments: {value_0}.",
        "Refit the selected garment parts against the driver whenever a slider moves.",
        "Rename",
        "Renderer ready, waiting for first frame | Backend: {value_0}",
        "Repaint",
        "Replace",
        "Replace this slider's authored mesh region",
        "Reset",
        "Reset Colour",
        "Reset or Bake the visible result. Saving a profile does not Bake.",
        "Resident package loaded: {value_0} part(s).",
        "Resident presentation updated: {value_0}.",
        "ResidentViewportNavigationTool",
        "Resize left Edit Mesh tools",
        "Resize right Edit Mesh tools",
        "Review & Apply",
        "Review the visible result. Bake writes it into the mesh; Reset discards it. Topology edits stay blocked until one runs.",
        "Right",
        "Rigid (hard surface)",
        "Rotate",
        "Save",
        "Save Edited Package",
        "Save Morph Preset",
        "Save Preset...",
        "Save Profile",
        "Saved edited package: {value_0}",
        "Scale",
        "Scale how strongly the selected bound garments follow the driver. Zero leaves them stationary unless clearance relief is needed.",
        "Scene update rejected: {value_0}.",
        "Select",
        "Select All",
        "Select one or more bound garment parts in the viewport, then apply the refit settings.",
        "Select one or more driver parts in the viewport, then choose Set Selected Driver Parts.",
        "Select one or more garment parts in the viewport, then choose Bind Selected Garment Parts.",
        "Select or author a topology-matched profile.",
        "Select shape",
        "Selected",
        "Selected part detail",
        "Selected {value_0} of {value_1}",
        "Selection",
        "Selection mode",
        "Selection target",
        "Selection updated by MeshService.",
        "Shape Sliders",
        "Shift + left-drag",
        "Shift + left-drag, or middle / right-drag",
        "Shift + left-drag, or middle-drag",
        "Shift + left-drag, or right-drag",
        "Showing {value_0} preview. Save or Cancel returns it to zero.",
        "Shrink",
        "Slider ID",
        "Slider ID cannot be empty.",
        "Slider label",
        "Smooth",
        "Smooth, Inflate and Pinch with radius, strength and falloff.",
        "Solid (Textured)",
        "Split Selection Into Part",
        "Step 1: Profile and sliders",
        "Step 2: Refit (optional)",
        "Step 3: Review and apply",
        "Strength",
        "Subdivide",
        "Subdivide and Refine Smooth require a selection and never change the whole mesh implicitly.",
        "Subdivide and Refine Smooth.",
        "Subtract",
        "Surface (flexible)",
        "Surface follows the bound body triangle. Rigid transports each vertex in the triangle's local frame for armour and other hard parts.",
        "Taper",
        "Texture",
        "Textures ready: {value_0} decoded, {value_1} optional fallback(s).",
        "Textures ready; drawing the first .NET/Vortice frame...",
        "Textures will load as soon as the resident preview is ready...",
        "The Edit Mesh tool rail could not be activated. {value_0}",
        "The axis buttons nudge the selection by the exact translate step.",
        "The weight the brush applies across its diameter. Strength scales the height; the falloff sets the shape.",
        "The {value_0} panel could not be shown ",
        "The {value_0} tool panel could not be shown (Win32 {value_1}).",
        "This profile has no sliders yet. Select parts, then Create Profile... to add one.",
        "This topology command requires a viewport mesh selection or an explicit PARTS selection.",
        "Tint...",
        "Toggle",
        "Tool: {value_0}",
        "Top",
        "Topology",
        "Topology preview updated by MeshService; Python session remains authoritative.",
        "Transform",
        "Translate step",
        "Translate step, Move, Grab and Grab radius.",
        "Twist",
        "Two panes",
        "Unbind every refit garment.",
        "Undo",
        "Up",
        "Use viewport mesh selection captured when this wizard opened",
        "Value preset",
        "Vertex overlay color",
        "Vertex px",
        "Vertex size in pixels",
        "Vertex update applied from MeshService.",
        "Vertices",
        "View layout: {value_0}.",
        "Viewport",
        "Viewport background color",
        "Viewport display: {value_0}.",
        "Viewport grid color",
        "Volume",
        "WPF GPU material viewport initialized.",
        "WPF GPU material viewport unavailable; using software fallback: {value_0}",
        "Wait for the viewport selection to finish, then open Create Profile again.",
        "Waiting for resident Morph & Refit state before Finish Edit Mesh...",
        "Waiting for the final Morph & Refit value before Finish Edit Mesh...",
        "Wheel",
        "Wire",
        "Wire + Vertices",
        "Wire overlay color",
        "Wire px",
        "Wire width in pixels",
        "Wires",
        "Write the visible slider result permanently into the mesh topology.",
        "X",
        "X-Ray",
        "X-Ray enabled: visible and occluded topology is drawn without depth rejection; wire and vertex colors switch automatically.",
        "Y",
        "Z",
        "Zoom",
        "approximate on metal parts; the built texture uses the exact value.",
        "blocked_renderer_unavailable: {value_0}",
        "category",
        "darken or shift it. Recolour repaints toward the chosen colour while keeping the ",
        "grab",
        "inflate",
        "label",
        "off",
        "on",
        "pinch",
        "profile-{value_0}",
        "reference",
        "rigid",
        "selection",
        "slider-{value_0}",
        "smooth",
        "surface",
        "texture's light and shade, so a dark part can become a bright one. The preview is ",
        "textured",
        "vertex",
        "wire",
        "{value_0}\r\n\r\nChoose the preview mode, topology appearance, viewport background and grid colors, or a camera preset. Colors and sizes are saved; X-Ray uses white wire and magenta vertices while preserving those sizes.",
        "{value_0} Falling back to WPF/GDI renderer.",
        "{value_0} Preference save failed: {value_1}",
        "{value_0} active: left-drag inside the brush circle.",
        "{value_0} commands",
        "{value_0} region selection awaiting authoritative depth-resolved result.",
        "{value_0} selection awaiting authoritative depth-resolved result.",
        "{value_0} tool",
        "{value_0} v · {value_1} tri",
        "▸  Morph & Refit",
        "▾  Morph & Refit",
    // END GENERATED UI LOCALIZATION KEYS
    };

    private static readonly HashSet<string> KeySet = new(KeyManifest, StringComparer.Ordinal);
    private static readonly Regex PlaceholderExpression =
        new(@"\{(?<name>[A-Za-z_][A-Za-z0-9_]*)\}", RegexOptions.CultureInvariant);
    private static readonly Regex PresentationNumberExpression = new(
        @"^(?<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)" +
        @"(?<suffix>\s*(?:B|KiB|MiB|GiB|TiB|KB|MB|GB|ms|s|min|%|px|Hz|FPS))?$",
        RegexOptions.CultureInvariant);
    private static readonly Regex TechnicalPresentationContextExpression = new(
        @"\b(?:id|uid|pid|port|protocol|revision|index|offset|address|" +
        @"hash|crc|sha|dxgi|lod|version)\b",
        RegexOptions.CultureInvariant | RegexOptions.IgnoreCase);
    private static readonly string[] PluralCategories =
        { "zero", "one", "two", "few", "many", "other" };
    private static readonly HashSet<string> PluralCategorySet = new(
        PluralCategories,
        StringComparer.Ordinal);
    private static readonly HashSet<string> UniversalCjkFontFamilies = new(
        new[] { "Arial Unicode MS", "Noto Sans CJK JP", "Noto Sans CJK KR",
            "Noto Sans CJK SC", "Noto Sans CJK TC" },
        StringComparer.OrdinalIgnoreCase);
    private static readonly IReadOnlyDictionary<string, string[]> CjkFontFallbacks =
        new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["ja"] = new[] { "Yu Gothic UI", "Meiryo UI", "Microsoft YaHei UI" },
            ["ko"] = new[] { "Malgun Gothic", "Microsoft YaHei UI" },
            ["zh-Hans"] = new[] { "Microsoft YaHei UI", "Microsoft JhengHei UI" },
            ["zh-Hant"] = new[] { "Microsoft JhengHei UI", "Microsoft YaHei UI" },
        };

    private readonly ExperimentForm _form;
    private readonly ToolTip _toolTip;
    private readonly ConditionalWeakTable<object, SourceProperties> _sources = new();
    private readonly Dictionary<FontKey, Font> _fallbackFonts = new();
    private readonly HashSet<Form> _knownForms = new();
    private readonly System.Windows.Forms.Timer _scanTimer = new() { Interval = 250 };
    private IReadOnlyDictionary<string, LocalizedEntry> _translations =
        new Dictionary<string, LocalizedEntry>(StringComparer.Ordinal);
    private IReadOnlyList<TemplateEntry> _templates = Array.Empty<TemplateEntry>();
    private string _languageCode = "en";
    private string _pluralRule = "other";
    private long _revision = -1;
    private bool _applying;
    private bool _disposed;

    public UiLocalizationOwner(ExperimentForm form, ToolTip toolTip)
    {
        _form = form;
        _toolTip = toolTip;
        _scanTimer.Tick += (_, _) => ApplyOpenForms(onlyNew: true);
        _form.Disposed += (_, _) => Dispose();
    }

    public static IReadOnlyList<string> LocalizationKeys => KeyManifest;

    public static string LocalizationKeyManifestHash { get; } = Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(
                string.Join("\n", KeyManifest.Order(StringComparer.Ordinal)))))
        .ToLowerInvariant();

    public bool TryApply(JsonElement root, out string status, out string reason)
    {
        status = "rejected";
        reason = string.Empty;
        if (Encoding.UTF8.GetByteCount(root.GetRawText()) > MaximumProtocolLineBytes)
        {
            reason = "protocol_line_too_large";
            return false;
        }

        var languageCode = JsonText(root, "language_code");
        var pluralRule = JsonText(root, "plural_rule");
        var catalogHash = JsonText(root, "catalog_hash");
        var manifestHash = JsonText(root, "key_manifest_hash");
        var sessionId = JsonText(root, "session_id");
        var processGeneration = JsonLong(root, "process_generation");
        var requestId = JsonLong(root, "request_id");
        var revision = JsonLong(root, "localization_revision");
        if (languageCode.Length == 0
            || pluralRule.Length == 0
            || catalogHash.Length == 0
            || manifestHash.Length == 0
            || sessionId.Length == 0
            || processGeneration < 0
            || requestId < 0
            || revision < 0)
        {
            reason = "missing_or_invalid_metadata";
            return false;
        }
        if (!string.Equals(
                manifestHash,
                LocalizationKeyManifestHash,
                StringComparison.OrdinalIgnoreCase))
        {
            reason = "key_manifest_hash_mismatch";
            return false;
        }
        if (revision < _revision)
        {
            status = "stale";
            reason = "localization_revision_is_older_than_applied_state";
            return false;
        }
        if (!TryReadTranslations(root, pluralRule, out var translations, out reason))
        {
            return false;
        }
        if (!root.TryGetProperty("translations", out var translationValues)
            || !string.Equals(
                CatalogHash(translationValues),
                catalogHash,
                StringComparison.OrdinalIgnoreCase))
        {
            reason = "catalog_hash_mismatch";
            return false;
        }

        _languageCode = languageCode;
        _pluralRule = pluralRule;
        _translations = translations;
        _templates = BuildTemplates(translations);
        _revision = revision;
        ApplyOpenForms();
        if (!_scanTimer.Enabled)
        {
            _scanTimer.Start();
        }
        status = "applied";
        return true;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _scanTimer.Stop();
        _scanTimer.Dispose();
        foreach (var font in _fallbackFonts.Values)
        {
            font.Dispose();
        }
        _fallbackFonts.Clear();
    }

    private bool TryReadTranslations(
        JsonElement root,
        string pluralRule,
        out IReadOnlyDictionary<string, LocalizedEntry> translations,
        out string reason)
    {
        reason = string.Empty;
        var parsed = new Dictionary<string, LocalizedEntry>(StringComparer.Ordinal);
        if (!root.TryGetProperty("translations", out var values)
            || values.ValueKind != JsonValueKind.Object)
        {
            translations = parsed;
            reason = "translations_must_be_an_object";
            return false;
        }
        foreach (var property in values.EnumerateObject())
        {
            if (!KeySet.Contains(property.Name))
            {
                translations = parsed;
                reason = "translation_key_is_not_helper_owned";
                return false;
            }
            if (property.Value.ValueKind == JsonValueKind.String)
            {
                var text = property.Value.GetString() ?? string.Empty;
                if (text.Length == 0)
                {
                    translations = parsed;
                    reason = "translation_value_is_empty";
                    return false;
                }
                if (!PlaceholderSetsMatch(property.Name, text))
                {
                    translations = parsed;
                    reason = "translation_placeholders_mismatch";
                    return false;
                }
                parsed[property.Name] = new LocalizedEntry(text, null);
                continue;
            }
            if (property.Value.ValueKind != JsonValueKind.Object)
            {
                translations = parsed;
                reason = "translation_value_has_invalid_type";
                return false;
            }
            var branches = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var branch in property.Value.EnumerateObject())
            {
                if (!PluralCategorySet.Contains(branch.Name)
                    || branch.Value.ValueKind != JsonValueKind.String
                    || string.IsNullOrEmpty(branch.Value.GetString())
                    || !PlaceholderSetsMatch(
                        property.Name,
                        branch.Value.GetString()!))
                {
                    translations = parsed;
                    reason = "plural_translation_is_invalid";
                    return false;
                }
                branches[branch.Name] = branch.Value.GetString()!;
            }
            if (!TryRequiredPluralCategories(pluralRule, out var requiredCategories))
            {
                translations = parsed;
                reason = "plural_rule_is_unknown";
                return false;
            }
            if (branches.Count == 0
                || requiredCategories.Any(category => !branches.ContainsKey(category)))
            {
                translations = parsed;
                reason = "plural_translation_is_incomplete";
                return false;
            }
            parsed[property.Name] = new LocalizedEntry(null, branches);
        }
        if (parsed.Count != KeySet.Count)
        {
            translations = parsed;
            reason = "helper_translation_keys_are_incomplete";
            return false;
        }
        translations = parsed;
        return true;
    }

    private static bool PlaceholderSetsMatch(string source, string translation)
    {
        var sourceNames = PlaceholderExpression
            .Matches(source)
            .Select(match => match.Groups["name"].Value)
            .ToHashSet(StringComparer.Ordinal);
        var translatedNames = PlaceholderExpression
            .Matches(translation)
            .Select(match => match.Groups["name"].Value)
            .ToHashSet(StringComparer.Ordinal);
        return sourceNames.SetEquals(translatedNames);
    }

    private static bool TryRequiredPluralCategories(
        string pluralRule,
        out IReadOnlyList<string> categories)
    {
        categories = pluralRule.Trim().ToLowerInvariant() switch
        {
            "other" => new[] { "other" },
            "one_other" => new[] { "one", "other" },
            "spanish_million" or "italian_million" or "zero_one_million" =>
                new[] { "one", "many", "other" },
            "polish" or "russian" =>
                new[] { "one", "few", "many", "other" },
            _ => Array.Empty<string>(),
        };
        return categories.Count > 0;
    }

    private static string CatalogHash(JsonElement translations)
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(
                   stream,
                   new JsonWriterOptions
                   {
                       Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
                       Indented = false,
                   }))
        {
            WriteCanonicalJson(writer, translations);
        }
        return Convert.ToHexString(SHA256.HashData(stream.ToArray()))
            .ToLowerInvariant();
    }

    internal static string CatalogHashFromJson(string json)
    {
        using var document = JsonDocument.Parse(json);
        return CatalogHash(document.RootElement);
    }

    private static void WriteCanonicalJson(Utf8JsonWriter writer, JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                writer.WriteStartObject();
                foreach (var property in value.EnumerateObject().OrderBy(
                             property => property.Name,
                             StringComparer.Ordinal))
                {
                    writer.WritePropertyName(property.Name);
                    WriteCanonicalJson(writer, property.Value);
                }
                writer.WriteEndObject();
                break;
            case JsonValueKind.Array:
                writer.WriteStartArray();
                foreach (var item in value.EnumerateArray())
                {
                    WriteCanonicalJson(writer, item);
                }
                writer.WriteEndArray();
                break;
            default:
                value.WriteTo(writer);
                break;
        }
    }

    private void ApplyOpenForms(bool onlyNew = false)
    {
        if (_disposed || _applying)
        {
            return;
        }
        _applying = true;
        try
        {
            _knownForms.RemoveWhere(form => form.IsDisposed);
            var openForms = Application.OpenForms
                .Cast<Form>()
                .Append(_form)
                .Distinct()
                .ToArray();
            foreach (var form in openForms)
            {
                if (onlyNew && _knownForms.Contains(form))
                {
                    continue;
                }
                form.SuspendLayout();
                try
                {
                    ApplyControlTree(form);
                }
                finally
                {
                    form.ResumeLayout(performLayout: true);
                    form.PerformLayout();
                }
                if (_knownForms.Add(form))
                {
                    form.FormClosed += (_, _) => _knownForms.Remove(form);
                }
            }
        }
        finally
        {
            _applying = false;
        }
    }

    private void ApplyControlTree(Control control)
    {
        var source = _sources.GetValue(control, _ => new SourceProperties());
        if (!source.ControlEventsRegistered)
        {
            source.ControlEventsRegistered = true;
            if (ShouldTranslateControlText(control))
            {
                control.TextChanged += (_, _) => ApplyDynamicControlText(control);
            }
            control.ControlAdded += (_, eventArgs) =>
            {
                if (eventArgs.Control is not null)
                {
                    ApplyAddedControl(eventArgs.Control);
                }
            };
            if (control is ListControl listControl)
            {
                listControl.FormattingEnabled = true;
                listControl.Format += FormatListItem;
            }
            if (control is ToolStrip registeredToolStrip)
            {
                registeredToolStrip.ItemAdded += (_, eventArgs) =>
                {
                    if (eventArgs.Item is not null)
                    {
                        ApplyAddedToolStripItem(eventArgs.Item);
                    }
                };
            }
        }

        if (ShouldTranslateControlText(control))
        {
            ApplyTextProperty(
                control.Text,
                value => control.Text = value,
                source,
                SourceProperty.Text);
        }
        ApplyTextProperty(
            control.AccessibleName,
            value => control.AccessibleName = value,
            source,
            SourceProperty.AccessibleName);
        ApplyTextProperty(
            control.AccessibleDescription,
            value => control.AccessibleDescription = value,
            source,
            SourceProperty.AccessibleDescription);
        ApplyTextProperty(
            _toolTip.GetToolTip(control),
            value => _toolTip.SetToolTip(control, value),
            source,
            SourceProperty.ToolTip);
        ApplyFont(control, source);

        if (control.ContextMenuStrip is not null)
        {
            ApplyToolStripItems(control.ContextMenuStrip.Items);
        }
        if (control is ToolStrip toolStrip)
        {
            ApplyToolStripItems(toolStrip.Items);
        }
        foreach (Control child in control.Controls)
        {
            ApplyControlTree(child);
        }
    }

    private void ApplyDynamicControlText(Control control)
    {
        if (_applying || _disposed || !ShouldTranslateControlText(control))
        {
            return;
        }
        _applying = true;
        try
        {
            var source = _sources.GetValue(control, _ => new SourceProperties());
            ApplyTextProperty(
                control.Text,
                value => control.Text = value,
                source,
                SourceProperty.Text);
            control.PerformLayout();
        }
        finally
        {
            _applying = false;
        }
    }

    private static bool ShouldTranslateControlText(Control control) =>
        control switch
        {
            TextBoxBase textBox => textBox.ReadOnly,
            ComboBox => false,
            ListControl => false,
            UpDownBase => false,
            _ => true,
        };

    private void ApplyAddedControl(Control control)
    {
        if (_disposed)
        {
            return;
        }
        var wasApplying = _applying;
        _applying = true;
        try
        {
            ApplyControlTree(control);
            control.Parent?.PerformLayout();
        }
        finally
        {
            _applying = wasApplying;
        }
    }

    private void FormatListItem(object? sender, ListControlConvertEventArgs eventArgs)
    {
        var source = Convert.ToString(eventArgs.ListItem, CultureInfo.CurrentCulture) ?? string.Empty;
        eventArgs.Value = TranslateRendered(source);
    }

    private void ApplyAddedToolStripItem(ToolStripItem item)
    {
        if (_disposed)
        {
            return;
        }
        var wasApplying = _applying;
        _applying = true;
        try
        {
            ApplyToolStripItem(item);
        }
        finally
        {
            _applying = wasApplying;
        }
    }

    private void ApplyToolStripItems(ToolStripItemCollection items)
    {
        foreach (ToolStripItem item in items)
        {
            ApplyToolStripItem(item);
        }
    }

    private void ApplyToolStripItem(ToolStripItem item)
    {
        var source = _sources.GetValue(item, _ => new SourceProperties());
        if (!source.ItemEventsRegistered)
        {
            source.ItemEventsRegistered = true;
            if (ShouldTranslateToolStripText(item))
            {
                item.TextChanged += (_, _) => ApplyDynamicToolStripText(item);
            }
        }
        if (ShouldTranslateToolStripText(item))
        {
            ApplyTextProperty(
                item.Text,
                value => item.Text = value,
                source,
                SourceProperty.Text);
        }
        ApplyTextProperty(
            item.AccessibleName,
            value => item.AccessibleName = value,
            source,
            SourceProperty.AccessibleName);
        ApplyTextProperty(
            item.AccessibleDescription,
            value => item.AccessibleDescription = value,
            source,
            SourceProperty.AccessibleDescription);
        ApplyTextProperty(
            item.ToolTipText,
            value => item.ToolTipText = value,
            source,
            SourceProperty.ToolTip);
        if (item is ToolStripDropDownItem dropDown)
        {
            ApplyToolStripItems(dropDown.DropDownItems);
        }
    }

    private static bool ShouldTranslateToolStripText(ToolStripItem item) =>
        item is not ToolStripTextBox and not ToolStripComboBox;

    private void ApplyDynamicToolStripText(ToolStripItem item)
    {
        if (_applying || _disposed || !ShouldTranslateToolStripText(item))
        {
            return;
        }
        _applying = true;
        try
        {
            var source = _sources.GetValue(item, _ => new SourceProperties());
            ApplyTextProperty(
                item.Text,
                value => item.Text = value,
                source,
                SourceProperty.Text);
        }
        finally
        {
            _applying = false;
        }
    }

    private void ApplyTextProperty(
        string? current,
        Action<string> write,
        SourceProperties source,
        SourceProperty property)
    {
        current ??= string.Empty;
        ref var english = ref source.Source(property);
        ref var rendered = ref source.Rendered(property);
        if (english is null)
        {
            english = current;
        }
        else if (!string.Equals(current, rendered, StringComparison.Ordinal)
                 && !string.Equals(current, english, StringComparison.Ordinal))
        {
            english = current;
        }
        var translated = TranslateRendered(english);
        rendered = translated;
        if (!string.Equals(current, translated, StringComparison.Ordinal))
        {
            write(translated);
        }
    }

    private string TranslateRendered(string source)
    {
        if (source.Length == 0)
        {
            return source;
        }
        if (_translations.TryGetValue(source, out var exact))
        {
            return exact.Select(_pluralRule, _languageCode, null);
        }
        foreach (var template in _templates)
        {
            var match = template.Pattern.Match(source);
            if (!match.Success)
            {
                continue;
            }
            var arguments = new Dictionary<string, string>(StringComparer.Ordinal);
            for (var index = 0; index < template.Placeholders.Length; index++)
            {
                arguments[template.Placeholders[index]] = match.Groups[index + 1].Value;
            }
            decimal? count = null;
            if (arguments.TryGetValue("count", out var countText)
                && decimal.TryParse(
                    countText,
                    NumberStyles.Number,
                    CultureInfo.InvariantCulture,
                    out var parsedCount))
            {
                count = parsedCount;
            }
            var translated = template.Translation.Select(
                _pluralRule,
                _languageCode,
                count);
            foreach (var argument in arguments)
            {
                var renderedArgument = TranslateRendered(argument.Value);
                translated = translated.Replace(
                    $"{{{argument.Key}}}",
                    LocalizePresentationArgument(
                        _languageCode,
                        renderedArgument,
                        template.Source),
                    StringComparison.Ordinal);
            }
            return translated;
        }
        return source;
    }

    internal static string LocalizePresentationArgument(
        string languageCode,
        string source,
        string presentationContext = "")
    {
        var culture = PresentationCulture(languageCode);
        if (DateTime.TryParseExact(
                source,
                "yyyy-MM-dd",
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var date))
        {
            return date.ToString("d", culture);
        }
        if (DateTime.TryParseExact(
                source,
                new[] { "yyyy-MM-dd HH:mm", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-ddTHH:mm", "yyyy-MM-ddTHH:mm:ss" },
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var dateTime))
        {
            return dateTime.ToString("g", culture);
        }
        if (DateTime.TryParseExact(
                source,
                new[] { "HH:mm", "HH:mm:ss" },
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var time))
        {
            return time.ToString(source.Length == 5 ? "t" : "T", culture);
        }

        var match = PresentationNumberExpression.Match(source);
        if (!match.Success)
        {
            return source;
        }
        var rawNumber = match.Groups["number"].Value;
        var suffix = match.Groups["suffix"].Value;
        if (!rawNumber.Contains(',')
            && !rawNumber.Contains('.')
            && suffix.Length == 0)
        {
            if (TechnicalPresentationContextExpression.IsMatch(
                    presentationContext))
            {
                return source;
            }
        }
        if (!decimal.TryParse(
                rawNumber.Replace(",", string.Empty, StringComparison.Ordinal),
                NumberStyles.Number,
                CultureInfo.InvariantCulture,
                out var number))
        {
            return source;
        }
        var decimalIndex = rawNumber.LastIndexOf('.');
        var decimals = decimalIndex < 0 ? 0 : rawNumber.Length - decimalIndex - 1;
        return number.ToString($"N{decimals}", culture) + suffix;
    }

    private static IReadOnlyList<TemplateEntry> BuildTemplates(
        IReadOnlyDictionary<string, LocalizedEntry> translations)
    {
        var templates = new List<TemplateEntry>();
        foreach (var pair in translations)
        {
            var placeholders = PlaceholderExpression
                .Matches(pair.Key)
                .Select(match => match.Groups["name"].Value)
                .ToArray();
            if (placeholders.Length == 0)
            {
                continue;
            }
            var expression = new StringBuilder("^");
            var offset = 0;
            foreach (Match match in PlaceholderExpression.Matches(pair.Key))
            {
                expression.Append(Regex.Escape(pair.Key[offset..match.Index]));
                expression.Append("(.*?)");
                offset = match.Index + match.Length;
            }
            expression.Append(Regex.Escape(pair.Key[offset..]));
            expression.Append('$');
            templates.Add(
                new TemplateEntry(
                    new Regex(
                        expression.ToString(),
                        RegexOptions.CultureInvariant | RegexOptions.Singleline),
                    pair.Key,
                    placeholders,
                    pair.Value,
                    pair.Key.Length - placeholders.Sum(name => name.Length + 2)));
        }
        return templates
            .OrderByDescending(entry => entry.LiteralLength)
            .ThenBy(entry => entry.Pattern.ToString(), StringComparer.Ordinal)
            .ToArray();
    }

    private static string JsonText(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;

    private static long JsonLong(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt64(out var number)
            ? number
            : -1;

    private sealed record LocalizedEntry(
        string? Scalar,
        IReadOnlyDictionary<string, string>? Plural)
    {
        public string Select(string pluralRule, string languageCode, decimal? count)
        {
            if (Scalar is not null)
            {
                return Scalar;
            }
            var category = SelectPluralCategory(
                pluralRule,
                languageCode,
                count ?? 0);
            if (Plural!.TryGetValue(category, out var value))
            {
                return value;
            }
            return Plural["other"];
        }

    }

    internal static string SelectPluralCategory(
        string pluralRule,
        string languageCode,
        decimal count)
    {
        var rule = pluralRule.Trim().ToLowerInvariant();
        var locale = languageCode.Trim().ToLowerInvariant();
        var absolute = Math.Abs(count);
        var scale = (decimal.GetBits(absolute)[3] >> 16) & 0x7F;
        var isInteger = scale == 0;
        var integer = decimal.Truncate(absolute);
        var value = isInteger && integer <= long.MaxValue ? (long)integer : -1;
        if (rule == "other")
        {
            return "other";
        }
        if (rule == "one_other")
        {
            return value == 1 ? "one" : "other";
        }
        if (rule == "spanish_million")
        {
            if (absolute == 1)
            {
                return "one";
            }
            return value > 0 && value % 1_000_000 == 0 ? "many" : "other";
        }
        if (rule == "italian_million")
        {
            if (value == 1)
            {
                return "one";
            }
            return value > 0 && value % 1_000_000 == 0 ? "many" : "other";
        }
        if (rule == "zero_one_million")
        {
            if (integer is >= 0 and < 2)
            {
                return "one";
            }
            return value > 0 && value % 1_000_000 == 0 ? "many" : "other";
        }
        if (rule == "polish" || locale == "pl")
        {
            if (value == 1)
            {
                return "one";
            }
            if (value >= 0
                && value % 10 is >= 2 and <= 4
                && value % 100 is not (>= 12 and <= 14))
            {
                return "few";
            }
            return isInteger ? "many" : "other";
        }
        if (rule == "russian" || locale == "ru")
        {
            if (value >= 0 && value % 10 == 1 && value % 100 != 11)
            {
                return "one";
            }
            if (value >= 0
                && value % 10 is >= 2 and <= 4
                && value % 100 is not (>= 12 and <= 14))
            {
                return "few";
            }
            return isInteger ? "many" : "other";
        }
        return "other";
    }

    private sealed record TemplateEntry(
        Regex Pattern,
        string Source,
        string[] Placeholders,
        LocalizedEntry Translation,
        int LiteralLength);

    private enum SourceProperty { Text, AccessibleName, AccessibleDescription, ToolTip }

    private sealed class SourceProperties
    {
        private readonly string?[] _source = new string?[4];
        private readonly string?[] _rendered = new string?[4];

        public bool ControlEventsRegistered { get; set; }
        public bool ItemEventsRegistered { get; set; }
        public Font? OriginalFont { get; set; }

        public ref string? Source(SourceProperty property) => ref _source[(int)property];
        public ref string? Rendered(SourceProperty property) => ref _rendered[(int)property];
    }

    private readonly record struct FontKey(
        string FamilyName, float Size, FontStyle Style, GraphicsUnit Unit, byte CharSet, bool Vertical);
}
