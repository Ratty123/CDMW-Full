using System.Diagnostics;
using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Hidden end-to-end diagnostics for every row exposed by Edit Mesh.
/// The proof uses the real form, production D3D11 viewport, material bindings,
/// pointer gesture methods, rail pages, and protocol writers.
/// </summary>
internal sealed partial class ExperimentForm
{
    internal Dictionary<string, object?> AllEditMeshToolsDiagnosticProof()
    {
        BuildAuthoringToolPanels();
        ActivateToolRailLayout();
        _scene.SetInteractionMode("mesh_edit");
        var displayApplied = _viewport.TrySetDisplayMode("textured", out var displayError);
        var materialApplied = _viewport.TryApplyMaterialState(
            Enumerable.Range(0, _document.Submeshes.Count).ToArray(),
            out var materialError);

        var protocolEvents = new List<(string Name, Dictionary<string, object?> Payload)>();
        void Capture(string name, Dictionary<string, object?> payload) =>
            protocolEvents.Add((name, new Dictionary<string, object?>(payload)));

        _viewport.EditorEventRequested += Capture;
        try
        {
            var interactionCases = new List<Dictionary<string, object?>>();
            foreach (var target in new[] { "vertex", "edge", "face" })
            {
                foreach (var shape in new[] { "brush", "lasso", "rectangle" })
                {
                    interactionCases.Add(RunEditMeshInteractionDiagnostic(
                        $"select_{shape}_{target}",
                        protocolEvents,
                        sustained: shape == "brush" && target == "face"));
                }
            }
            foreach (var tool in new[] { "move", "grab", "smooth", "inflate", "pinch" })
            {
                interactionCases.Add(RunEditMeshInteractionDiagnostic(
                    tool,
                    protocolEvents,
                    sustained: tool == "grab"));
            }

            var commandPages = RunEditMeshCommandPageDiagnostics();
            var finalFrame = RunEditMeshDiagnosticFrame();
            var requiredRows = EditMeshToolListContract.RowOrder
                .Select(row => row.Key)
                .ToArray();
            var coveredRows = interactionCases
                .Select(item => Convert.ToString(item.GetValueOrDefault("rail_row")) ?? string.Empty)
                .Concat(commandPages.Select(item =>
                    Convert.ToString(item.GetValueOrDefault("rail_row")) ?? string.Empty))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
            var allRowsCovered = requiredRows.All(row =>
                coveredRows.Contains(row, StringComparer.OrdinalIgnoreCase));
            var interactionsOk = interactionCases.All(item => item.GetValueOrDefault("ok") is true);
            var pagesOk = commandPages.All(item => item.GetValueOrDefault("ok") is true);
            return new Dictionary<string, object?>
            {
                ["ok"] = displayApplied
                    && materialApplied
                    && _viewport.TexturesEnabled
                    && _viewport.HasTexturedMaterialResources
                    && interactionsOk
                    && pagesOk
                    && finalFrame.GetValueOrDefault("ok") is true
                    && allRowsCovered
                    && string.Equals(
                        _viewport.RendererBackendName,
                        "d3d11_vortice_shader",
                        StringComparison.Ordinal),
                ["hidden"] = !Visible && !ShowInTaskbar,
                ["renderer_backend"] = _viewport.RendererBackendName,
                ["display_mode"] = _viewport.DisplayMode,
                ["textures_enabled"] = _viewport.TexturesEnabled,
                ["bound_texture_resources"] = _viewport.HasTexturedMaterialResources,
                ["display_applied"] = displayApplied,
                ["display_error"] = displayError,
                ["material_applied"] = materialApplied,
                ["material_error"] = materialError,
                ["required_rail_rows"] = requiredRows,
                ["covered_rail_rows"] = coveredRows,
                ["all_rail_rows_covered"] = allRowsCovered,
                ["interaction_cases"] = interactionCases,
                ["command_pages"] = commandPages,
                ["captured_viewport_protocol_events"] = protocolEvents.Count,
                ["final_frame"] = finalFrame,
                ["renderer_resources"] = _viewport.RendererResourceMetricsPayload(),
            };
        }
        finally
        {
            _viewport.EditorEventRequested -= Capture;
        }
    }

    private Dictionary<string, object?> RunEditMeshInteractionDiagnostic(
        string mode,
        List<(string Name, Dictionary<string, object?> Payload)> protocolEvents,
        bool sustained)
    {
        var size = _viewport.ClientSize;
        var start = mode is "grab" or "smooth" or "inflate" or "pinch"
            ? _viewport.InteractionSoakMeshAnchor()
            : new Point(Math.Max(16, size.Width / 2), Math.Max(16, size.Height / 2));
        var points = EditMeshDiagnosticPath(mode, start, size, sustained);
        var protocolStart = protocolEvents.Count;
        var sampleTimes = new List<double>(points.Count);
        var total = Stopwatch.StartNew();
        _viewport.BeginInteractionSoak(mode, start);
        foreach (var point in points)
        {
            var sampleStarted = Stopwatch.GetTimestamp();
            _viewport.StepInteractionSoak(point);
            sampleTimes.Add(ElapsedMilliseconds(sampleStarted));
        }
        var finishStarted = Stopwatch.GetTimestamp();
        var result = _viewport.FinishInteractionSoak(points[^1]);
        var finishMs = ElapsedMilliseconds(finishStarted);
        var frame = RunEditMeshDiagnosticFrame();
        total.Stop();

        var emitted = protocolEvents.Skip(protocolStart).ToArray();
        var selectionCase = mode.StartsWith("select_", StringComparison.Ordinal);
        var pieces = mode.Split('_', StringSplitOptions.RemoveEmptyEntries);
        var selectionShape = selectionCase && pieces.Length == 3 ? pieces[1] : string.Empty;
        var selectionTarget = selectionCase && pieces.Length == 3 ? pieces[2] : string.Empty;
        var selectionShapePreserved = !selectionCase
            || emitted
                .Where(item => item.Name is "select_request" or "selection_request")
                .Any(item => SelectionDiagnosticPayloadMatches(
                    item.Payload,
                    selectionShape,
                    selectionTarget));
        var selectedExpectedScope = selectionTarget switch
        {
            "vertex" => result.SelectedVertexCount > 0,
            "edge" => result.SelectedEdgeCount > 0,
            "face" => result.SelectedFaceCount > 0,
            _ => result.ChangedVertexCount > 0,
        };
        var railRow = selectionCase ? "select" : mode;
        var maxSampleMs = sampleTimes.Count == 0 ? 0.0 : sampleTimes.Max();
        var p95SampleMs = Percentile(sampleTimes, 0.95);
        var pointerLatencyOk = p95SampleMs <= 20.0 && maxSampleMs <= 100.0;
        var terminalLatencyOk = finishMs <= 250.0;
        return new Dictionary<string, object?>
        {
            ["ok"] = result.FinalAuthorityMatches
                && result.ProvisionalCleared
                && selectionShapePreserved
                && selectedExpectedScope
                && pointerLatencyOk
                && terminalLatencyOk
                && frame.GetValueOrDefault("ok") is true
                && _viewport.TexturesEnabled
                && _viewport.HasTexturedMaterialResources,
            ["mode"] = mode,
            ["rail_row"] = railRow,
            ["sustained"] = sustained,
            ["sample_count"] = sampleTimes.Count,
            ["total_ms"] = total.Elapsed.TotalMilliseconds,
            ["maximum_sample_ms"] = maxSampleMs,
            ["p95_sample_ms"] = p95SampleMs,
            ["finish_ms"] = finishMs,
            ["latency_gates"] = new Dictionary<string, bool>
            {
                ["pointer_p95_at_most_20_ms"] = p95SampleMs <= 20.0,
                ["no_pointer_sample_over_100_ms"] = maxSampleMs <= 100.0,
                ["terminal_reconciliation_at_most_250_ms"] = terminalLatencyOk,
            },
            ["cursor_coverage_pixels"] = result.CursorCoveragePixels,
            ["changed_vertex_count"] = result.ChangedVertexCount,
            ["selected_vertex_count"] = result.SelectedVertexCount,
            ["selected_edge_count"] = result.SelectedEdgeCount,
            ["selected_face_count"] = result.SelectedFaceCount,
            ["selected_part_count"] = result.SelectedPartCount,
            ["final_authority_matches"] = result.FinalAuthorityMatches,
            ["stale_result_ignored"] = result.StaleResultIgnored,
            ["provisional_cleared"] = result.ProvisionalCleared,
            ["selection_shape_preserved"] = selectionShapePreserved,
            ["selection_target"] = selectionTarget,
            ["selection_shape"] = selectionShape,
            ["expected_scope_changed"] = selectedExpectedScope,
            ["protocol_event_count"] = emitted.Length,
            ["protocol_event_names"] = emitted.Select(item => item.Name).ToArray(),
            ["frame"] = frame,
            ["textures_enabled_after"] = _viewport.TexturesEnabled,
            ["bound_texture_resources_after"] = _viewport.HasTexturedMaterialResources,
        };
    }

    private List<Dictionary<string, object?>> RunEditMeshCommandPageDiagnostics()
    {
        var rows = new List<Dictionary<string, object?>>();
        rows.Add(RunEditMeshCommandPageDiagnostic(
            "topology",
            ToolRailPage.Topology,
            () => WriteCommandRequest("recalculate_normals") > 0));
        rows.Add(RunEditMeshCommandPageDiagnostic(
            "colour",
            ToolRailPage.Colour,
            () =>
            {
                QueuePartColourEdit(new Dictionary<string, object?>
                {
                    ["tint_rgb"] = new[] { 224, 240, 255 },
                });
                var queued = _pendingPartColourEdit is { Count: > 0 };
                FlushPartColourEdit();
                return queued && _pendingPartColourEdit is null;
            }));
        rows.Add(RunEditMeshCommandPageDiagnostic(
            "morph",
            ToolRailPage.MorphRefit,
            () => WriteCommandRequest("morph_state_request") > 0));
        return rows;
    }

    private Dictionary<string, object?> RunEditMeshCommandPageDiagnostic(
        string row,
        ToolRailPage page,
        Func<bool> exercise)
    {
        var started = Stopwatch.StartNew();
        ShowToolRailPage(page);
        PerformLayout();
        var exercised = exercise();
        var frame = RunEditMeshDiagnosticFrame();
        started.Stop();
        return new Dictionary<string, object?>
        {
            ["ok"] = exercised
                && _selectedToolRailPage == page
                && _toolRailPages.GetValueOrDefault(page)?.Parent is not null
                && frame.GetValueOrDefault("ok") is true
                && _viewport.TexturesEnabled
                && _viewport.HasTexturedMaterialResources,
            ["rail_row"] = row,
            ["page"] = page.ToString(),
            ["exercised"] = exercised,
            ["elapsed_ms"] = started.Elapsed.TotalMilliseconds,
            ["frame"] = frame,
            ["textures_enabled_after"] = _viewport.TexturesEnabled,
            ["bound_texture_resources_after"] = _viewport.HasTexturedMaterialResources,
        };
    }

    private Dictionary<string, object?> RunEditMeshDiagnosticFrame()
    {
        var ok = _viewport.TryRunHeadlessRendererFrame(
            out var frameMs,
            out var presentMs,
            out var error);
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["frame_ms"] = frameMs,
            ["present_ms"] = presentMs,
            ["error"] = error,
            ["textures_enabled"] = _viewport.TexturesEnabled,
            ["bound_texture_resources"] = _viewport.HasTexturedMaterialResources,
        };
    }

    private static List<Point> EditMeshDiagnosticPath(
        string mode,
        Point start,
        Size size,
        bool sustained)
    {
        var radiusX = Math.Max(24, size.Width / 5);
        var radiusY = Math.Max(24, size.Height / 5);
        if (mode.Contains("_lasso_", StringComparison.Ordinal))
        {
            var corners = new[]
            {
                new Point(start.X - radiusX, start.Y - radiusY),
                new Point(start.X + radiusX, start.Y - radiusY),
                new Point(start.X + radiusX, start.Y + radiusY),
                new Point(start.X - radiusX, start.Y + radiusY),
                new Point(start.X - radiusX, start.Y - radiusY),
            };
            return InterpolateDiagnosticPath(corners, 12);
        }
        if (mode.Contains("_rectangle_", StringComparison.Ordinal))
        {
            return new List<Point>
            {
                new(start.X + radiusX, start.Y + radiusY),
            };
        }
        var count = sustained ? 360 : 72;
        var points = new List<Point>(count);
        for (var index = 1; index <= count; index++)
        {
            var phase = index / (double)count * Math.Tau * (sustained ? 6.0 : 2.0);
            points.Add(new Point(
                start.X + (int)Math.Round(Math.Sin(phase) * radiusX),
                start.Y + (int)Math.Round(Math.Sin(phase * 2.0) * radiusY)));
        }
        if (!mode.StartsWith("select_", StringComparison.Ordinal))
        {
            // End away from the origin. A closed synthetic path is useful for
            // cursor coverage but correctly produces no net Move/Grab delta,
            // which would make a healthy authority reconciliation look like a
            // snap-back defect.
            points.Add(new Point(start.X + radiusX / 2, start.Y + radiusY / 3));
        }
        return points;
    }

    private static List<Point> InterpolateDiagnosticPath(IReadOnlyList<Point> anchors, int steps)
    {
        var points = new List<Point>((anchors.Count - 1) * steps);
        for (var segment = 1; segment < anchors.Count; segment++)
        {
            var first = anchors[segment - 1];
            var last = anchors[segment];
            for (var step = 1; step <= steps; step++)
            {
                var ratio = step / (double)steps;
                points.Add(new Point(
                    (int)Math.Round(first.X + (last.X - first.X) * ratio),
                    (int)Math.Round(first.Y + (last.Y - first.Y) * ratio)));
            }
        }
        return points;
    }

    private static bool SelectionDiagnosticPayloadMatches(
        Dictionary<string, object?>? payload,
        string shape,
        string target)
    {
        if (payload is null
            || !string.Equals(
                Convert.ToString(payload.GetValueOrDefault("target_mode")),
                target,
                StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (shape == "brush")
        {
            return payload.GetValueOrDefault("screen_brush") is Dictionary<string, object?>;
        }
        if (payload.GetValueOrDefault("screen_region") is not Dictionary<string, object?> region)
        {
            return false;
        }
        if (shape == "lasso")
        {
            return string.Equals(
                    Convert.ToString(region.GetValueOrDefault("mode")),
                    "lasso",
                    StringComparison.OrdinalIgnoreCase)
                && region.GetValueOrDefault("points") is Array points
                && points.Length >= 3;
        }
        return !string.Equals(
            Convert.ToString(region.GetValueOrDefault("mode")),
            "lasso",
            StringComparison.OrdinalIgnoreCase);
    }

    private static double ElapsedMilliseconds(long started) =>
        (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;

    private static double Percentile(IReadOnlyList<double> values, double percentile)
    {
        if (values.Count == 0)
        {
            return 0.0;
        }
        var ordered = values.OrderBy(value => value).ToArray();
        var index = Math.Clamp(
            (int)Math.Ceiling(ordered.Length * percentile) - 1,
            0,
            ordered.Length - 1);
        return ordered[index];
    }
}
