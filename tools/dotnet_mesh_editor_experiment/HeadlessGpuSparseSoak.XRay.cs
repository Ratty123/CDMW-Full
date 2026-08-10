using System.Globalization;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal static partial class HeadlessGpuSparseSoak
{
    private sealed record XRayOverlaySetup(
        MeshOverlaySizing ConfiguredSizing,
        NetEdgeTopology Topology,
        HashSet<int> SelectedEdges,
        HashSet<int> ProvisionalEdges,
        Dictionary<int, HashSet<int>> SelectedVertices,
        Dictionary<int, HashSet<int>> ProvisionalVertices,
        Dictionary<int, HashSet<int>> SelectedFaces,
        Dictionary<int, HashSet<int>> ProvisionalFaces,
        Dictionary<string, object?> Before,
        Dictionary<string, object?> WireVerticesAfter,
        bool WireVerticesNoSolidFill,
        bool SelectionColorsReachedDraws,
        double WireVerticesFrameMs);

    private static XRayOverlaySetup PrepareXRayOverlayProof(
        D3D11MaterialViewport viewport,
        ObjDocument document,
        NetViewportCamera camera,
        Size clientSize)
    {
        var configuredColors = new MeshOverlayColors(
            System.Drawing.Color.FromArgb(12, 34, 56),
            System.Drawing.Color.FromArgb(78, 90, 123),
            System.Drawing.Color.FromArgb(145, 156, 167),
            System.Drawing.Color.FromArgb(178, 189, 200));
        var configuredSizing = new MeshOverlaySizing(
            WireWidthPixels: 2.75f,
            VertexMarkerSizePixels: 11.0f);
        viewport.SetOverlaySettings(new MeshOverlaySettings(configuredColors, configuredSizing));
        var topology = NetEdgeTopology.Build(document);
        var selectedEdges = topology.Edges.Count > 0
            ? new HashSet<int> { topology.Edges[0].Id }
            : new HashSet<int>();
        var provisionalEdges = topology.Edges.Count > 1
            ? new HashSet<int> { topology.Edges[1].Id }
            : new HashSet<int>(selectedEdges);
        var selectedVertices = new Dictionary<int, HashSet<int>> { [0] = new() { 0 } };
        var provisionalVertices = new Dictionary<int, HashSet<int>> { [0] = new() { 1 } };
        var selectedFaces = new Dictionary<int, HashSet<int>> { [0] = new() { 0 } };
        var provisionalFaces = new Dictionary<int, HashSet<int>> { [0] = new() { 0 } };
        var before = viewport.ResourceMetricsPayload();
        viewport.UpdateRenderPanes(new[]
        {
            new D3D11RenderPane(
                new Rectangle(Point.Empty, clientSize),
                camera,
                "editable",
                "wire_vertices",
                MaterialDebugMode: 0,
                TexturesEnabled: false,
                GridVisible: false,
                GizmoVisible: false,
                XRay: false,
                InteractionAllowed: true),
        });
        viewport.UpdateOverlay(
            topology,
            selectedEdges,
            -1,
            null,
            selectedVertices,
            selectedFaces,
            new HashSet<int>(),
            -1,
            showWire: true,
            showVertices: true,
            showXRay: false,
            brushCursor: null,
            brushRadius: 24.0f,
            provisionalVertices: provisionalVertices,
            provisionalFaces: provisionalFaces,
            provisionalEdges: provisionalEdges);
        if (!viewport.TryRunHeadlessFrame(out var wireVerticesFrameMs, out _, out var wireVerticesError))
        {
            throw new InvalidOperationException($"Hidden D3D11 Wire + Vertices proof failed: {wireVerticesError}");
        }
        var wireVerticesAfter = viewport.ResourceMetricsPayload();
        var wireVerticesNoSolidFill =
            Metric(wireVerticesAfter, "textured_solid_batch_draws") == Metric(before, "textured_solid_batch_draws")
            && Metric(wireVerticesAfter, "untextured_solid_batch_draws") == Metric(before, "untextured_solid_batch_draws")
            && Metric(wireVerticesAfter, "transparent_solid_batch_draws") == Metric(before, "transparent_solid_batch_draws")
            && Metric(wireVerticesAfter, "wire_overlay_draws") > Metric(before, "wire_overlay_draws")
            && Metric(wireVerticesAfter, "vertex_overlay_batch_draws") > Metric(before, "vertex_overlay_batch_draws");
        var selectionColorsReachedDraws =
            Metric(wireVerticesAfter, "committed_selection_overlay_primitives")
                > Metric(before, "committed_selection_overlay_primitives")
            && Metric(wireVerticesAfter, "live_selection_overlay_primitives")
                > Metric(before, "live_selection_overlay_primitives")
            && string.Equals(
                wireVerticesAfter.GetValueOrDefault("last_committed_selection_primitive_color") as string,
                "#919CA7",
                StringComparison.Ordinal)
            && string.Equals(
                wireVerticesAfter.GetValueOrDefault("last_live_selection_primitive_color") as string,
                "#B2BDC8",
                StringComparison.Ordinal);
        return new XRayOverlaySetup(
            configuredSizing,
            topology,
            selectedEdges,
            provisionalEdges,
            selectedVertices,
            provisionalVertices,
            selectedFaces,
            provisionalFaces,
            before,
            wireVerticesAfter,
            wireVerticesNoSolidFill,
            selectionColorsReachedDraws,
            wireVerticesFrameMs);
    }

    private static Dictionary<string, object?> ApplyXRayOverlayProof(
        D3D11MaterialViewport viewport,
        ObjDocument document,
        NetViewportCamera camera,
        Size clientSize,
        bool smoke)
    {
        if (!smoke)
        {
            return new Dictionary<string, object?>
            {
                ["ok"] = true,
                ["xray_ok"] = true,
                ["configured_sizing_active"] = true,
                ["wire_vertices_no_solid_fill"] = true,
                ["selection_colors_reached_draws"] = true,
                ["exercised"] = false,
                ["reason"] = "The dedicated X-Ray draw proof runs in smoke mode.",
            };
        }

        var setup = PrepareXRayOverlayProof(viewport, document, camera, clientSize);
        var configuredSizing = setup.ConfiguredSizing;
        var topology = setup.Topology;
        var selectedEdges = setup.SelectedEdges;
        var provisionalEdges = setup.ProvisionalEdges;
        var selectedVertices = setup.SelectedVertices;
        var provisionalVertices = setup.ProvisionalVertices;
        var selectedFaces = setup.SelectedFaces;
        var provisionalFaces = setup.ProvisionalFaces;
        var before = setup.Before;
        var wireVerticesAfter = setup.WireVerticesAfter;
        var wireVerticesNoSolidFill = setup.WireVerticesNoSolidFill;
        var selectionColorsReachedDraws = setup.SelectionColorsReachedDraws;
        var wireVerticesFrameMs = setup.WireVerticesFrameMs;
        viewport.UpdateRenderPanes(new[]
        {
            new D3D11RenderPane(
                new Rectangle(Point.Empty, clientSize),
                camera,
                "editable",
                "wire_vertices",
                MaterialDebugMode: 0,
                TexturesEnabled: false,
                GridVisible: false,
                GizmoVisible: false,
                XRay: true,
                InteractionAllowed: true),
        });
        viewport.UpdateOverlay(
            topology,
            selectedEdges,
            -1,
            null,
            selectedVertices,
            selectedFaces,
            new HashSet<int>(),
            -1,
            showWire: true,
            showVertices: true,
            showXRay: true,
            brushCursor: null,
            brushRadius: 24.0f,
            provisionalVertices: provisionalVertices,
            provisionalFaces: provisionalFaces,
            provisionalEdges: provisionalEdges);
        if (!viewport.TryRunHeadlessFrame(out var frameMs, out _, out var error))
        {
            throw new InvalidOperationException($"Hidden D3D11 X-Ray overlay proof failed: {error}");
        }
        var after = viewport.ResourceMetricsPayload();
        var normalColorsRetained =
            string.Equals(after.GetValueOrDefault("wire_overlay_color") as string, "#0C2238", StringComparison.Ordinal)
            && string.Equals(after.GetValueOrDefault("vertex_overlay_color") as string, "#4E5A7B", StringComparison.Ordinal);
        // X-Ray draws the colours the reader chose. The automatic high-contrast
        // palette is the fallback for an untouched preference only, proved
        // against the restored defaults below; asserting it here regardless is
        // what let a chosen wire colour be discarded in X-Ray unnoticed.
        var chosenPaletteActive =
            after.GetValueOrDefault("xray_overlay_active") is true
            && string.Equals(after.GetValueOrDefault("xray_wire_overlay_color") as string, "#0C2238", StringComparison.Ordinal)
            && string.Equals(after.GetValueOrDefault("xray_vertex_overlay_color") as string, "#4E5A7B", StringComparison.Ordinal);
        var wireNoDepthAdvanced =
            Metric(after, "xray_wire_no_depth_draws") > Metric(wireVerticesAfter, "xray_wire_no_depth_draws");
        var vertexNoDepthAdvanced =
            Metric(after, "xray_vertex_no_depth_passes") > Metric(wireVerticesAfter, "xray_vertex_no_depth_passes");
        var configuredSizingActive =
            Math.Abs(
                Convert.ToSingle(after.GetValueOrDefault("wire_overlay_width_pixels"), CultureInfo.InvariantCulture)
                - configuredSizing.WireWidthPixels) <= 0.0001f
            && Math.Abs(
                Convert.ToSingle(after.GetValueOrDefault("vertex_marker_fit_size_pixels"), CultureInfo.InvariantCulture)
                - configuredSizing.VertexMarkerSizePixels) <= 0.0001f;
        viewport.SetOverlaySettings(MeshOverlaySettings.Default);
        ConfigureSmokeViewport(viewport, camera, clientSize, smoke: true);
        if (!viewport.TryRunHeadlessFrame(out _, out _, out var restoreError))
        {
            throw new InvalidOperationException($"Hidden D3D11 X-Ray overlay proof restore failed: {restoreError}");
        }
        // The other direction: an untouched preference keeps the automatic
        // palette, because the default wire is black and X-Ray draws it through
        // the surface where black is unreadable.
        var restored = viewport.ResourceMetricsPayload();
        var automaticPaletteActive =
            string.Equals(restored.GetValueOrDefault("xray_wire_overlay_color") as string, "#F5F8FC", StringComparison.Ordinal)
            && string.Equals(restored.GetValueOrDefault("xray_vertex_overlay_color") as string, "#FF58D6", StringComparison.Ordinal);
        var xrayOk = normalColorsRetained
            && chosenPaletteActive
            && automaticPaletteActive
            && wireNoDepthAdvanced
            && vertexNoDepthAdvanced;

        return new Dictionary<string, object?>
        {
            ["ok"] = xrayOk && configuredSizingActive,
            ["xray_ok"] = xrayOk,
            ["exercised"] = true,
            ["frame_ms"] = frameMs,
            ["normal_colors_retained"] = normalColorsRetained,
            ["chosen_palette_active"] = chosenPaletteActive,
            ["automatic_palette_active"] = automaticPaletteActive,
            ["wire_no_depth_draw_advanced"] = wireNoDepthAdvanced,
            ["vertex_no_depth_pass_advanced"] = vertexNoDepthAdvanced,
            ["configured_sizing_active"] = configuredSizingActive,
            ["wire_vertices_no_solid_fill"] = wireVerticesNoSolidFill,
            ["wire_vertices_frame_ms"] = wireVerticesFrameMs,
            ["selection_colors_reached_draws"] = selectionColorsReachedDraws,
            ["configured_selection_color"] = wireVerticesAfter.GetValueOrDefault("selection_overlay_color"),
            ["configured_live_selection_color"] = wireVerticesAfter.GetValueOrDefault("live_selection_overlay_color"),
            ["last_committed_selection_draw_color"] = wireVerticesAfter.GetValueOrDefault(
                "last_committed_selection_primitive_color"),
            ["last_live_selection_draw_color"] = wireVerticesAfter.GetValueOrDefault(
                "last_live_selection_primitive_color"),
            ["committed_selection_primitives_before"] = Metric(
                before,
                "committed_selection_overlay_primitives"),
            ["committed_selection_primitives_after"] = Metric(
                wireVerticesAfter,
                "committed_selection_overlay_primitives"),
            ["live_selection_primitives_before"] = Metric(before, "live_selection_overlay_primitives"),
            ["live_selection_primitives_after"] = Metric(
                wireVerticesAfter,
                "live_selection_overlay_primitives"),
            ["configured_wire_width_pixels"] = after.GetValueOrDefault("wire_overlay_width_pixels"),
            ["configured_vertex_marker_size_pixels"] = after.GetValueOrDefault("vertex_marker_fit_size_pixels"),
            ["configured_wire_color"] = after.GetValueOrDefault("wire_overlay_color"),
            ["configured_vertex_color"] = after.GetValueOrDefault("vertex_overlay_color"),
            ["xray_wire_color"] = after.GetValueOrDefault("xray_wire_overlay_color"),
            ["xray_vertex_color"] = after.GetValueOrDefault("xray_vertex_overlay_color"),
            ["wire_no_depth_draws_before"] = Metric(before, "xray_wire_no_depth_draws"),
            ["wire_no_depth_draws_after"] = Metric(after, "xray_wire_no_depth_draws"),
            ["vertex_no_depth_passes_before"] = Metric(before, "xray_vertex_no_depth_passes"),
            ["vertex_no_depth_passes_after"] = Metric(after, "xray_vertex_no_depth_passes"),
        };
    }
}
