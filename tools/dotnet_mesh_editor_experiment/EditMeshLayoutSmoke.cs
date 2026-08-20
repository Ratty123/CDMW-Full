using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static partial class EditMeshLayoutSmoke
{
    private static readonly string[] ToolPages =
    {
        "Selection",
        "Transform",
        "Brush",
        "Topology",
        "Colour",
        "Morph & Refit",
    };

    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(
            arg,
            "--headless-edit-mesh-layout-smoke",
            StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = RequiredValue(args, "--layout-report");
        Directory.CreateDirectory(
            Path.GetDirectoryName(reportPath)
                ?? throw new InvalidOperationException("Layout report has no parent directory."));
        try
        {
            return RunGate(args, reportPath);
        }
        catch (Exception ex)
        {
            // This gate runs headless from a WinExe, so an escaping exception
            // would otherwise surface only as exit code 1 with no reason.
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(
                    new Dictionary<string, object?>
                    {
                        ["ok"] = false,
                        ["error"] = ex.Message,
                        ["error_type"] = ex.GetType().FullName,
                    },
                    new JsonSerializerOptions { WriteIndented = true }));
            return 1;
        }
    }

    private static int RunGate(string[] args, string reportPath)
    {
        using var constructionSplit = new SplitContainer
        {
            Name = "ZeroSizeConstructionSplit",
            Orientation = Orientation.Horizontal,
            FixedPanel = FixedPanel.Panel2,
            SplitterWidth = 6,
        };
        constructionSplit.Panel1MinSize = 0;
        constructionSplit.Panel2MinSize = 0;
        constructionSplit.Size = Size.Empty;
        EditMeshLayoutContracts.ApplyPanelTwoSize(
            constructionSplit,
            panelTwoSize: 280,
            requestedPanelOneMinimum: 240,
            requestedPanelTwoMinimum: 220);
        Require(
            constructionSplit.Panel1MinSize == 0
                && constructionSplit.Panel2MinSize == 0,
            "A hidden zero-size compact splitter retained invalid minimum sizes.");
        constructionSplit.Size = new Size(1180, 712);
        EditMeshLayoutContracts.ApplyPanelTwoSize(
            constructionSplit,
            panelTwoSize: 280,
            requestedPanelOneMinimum: 240,
            requestedPanelTwoMinimum: 220);
        Require(
            constructionSplit.SplitterDistance >= constructionSplit.Panel1MinSize
                && constructionSplit.SplitterDistance
                    <= constructionSplit.ClientSize.Height
                        - constructionSplit.SplitterWidth
                        - constructionSplit.Panel2MinSize,
            "The compact splitter distance is invalid after receiving its real size.");

        using var host = new Panel { Name = "LayoutSmokeHost" };
        using var placementRoot = new Panel { Name = "PlacementTools", Dock = DockStyle.Fill };
        using var railRoot = new Panel
        {
            Name = "ToolRailTools",
            Dock = DockStyle.Fill,
            Visible = false,
        };
        using var permanentViewportHost = new Panel
        {
            Name = "PermanentViewportHost",
            Dock = DockStyle.Fill,
        };
        host.Controls.Add(permanentViewportHost);
        host.Controls.Add(placementRoot);
        host.Controls.Add(railRoot);

        var placementLeft = CreateStack("PlacementLeftStack");
        var placementRight = CreateStack("PlacementRightStack");
        placementRoot.Controls.Add(placementLeft);
        placementRoot.Controls.Add(placementRight);

        var viewport = new Panel { Name = "ResidentViewportRegion" };
        var sessionCommands = Enumerable.Range(0, 6)
            .Select(index => new Button { Name = $"SessionCommand{index}" })
            .ToArray();
        var editSections = new[]
        {
            NewSection("Part Pick"),
            NewSection("Selection"),
            NewSection("Transform"),
            NewSection("Brush"),
            NewSection("Topology"),
            NewSection("Colour"),
        };
        var inspectorSections = new[]
        {
            NewSection("Parts"),
            NewSection("Action History"),
            NewSection("Viewport"),
        };
        var morphSection = NewSection("Morph & Refit");
        foreach (var section in editSections)
        {
            AddRow(placementLeft, section);
        }
        AddRow(placementRight, inspectorSections[1]);
        AddRow(placementRight, morphSection);
        AddRow(placementRight, inspectorSections[0]);
        AddRow(placementRight, inspectorSections[2]);
        permanentViewportHost.Controls.Add(viewport);

        var partPickHomeCell = placementLeft.GetCellPosition(editSections[0]);
        var viewportSectionHomeCell = placementRight.GetCellPosition(inspectorSections[2]);

        var compactSession = new FlowLayoutPanel { Name = "CompactSession" };
        var compactInspector = CreateStack("CompactInspector");
        var pageHost = new Panel { Name = "CompactPageHost" };
        var pages = ToolPages.ToDictionary(
            page => page,
            page => new Panel
            {
                Name = $"Page{page.Replace(" ", string.Empty).Replace("&", string.Empty)}",
                Dock = DockStyle.Fill,
                Visible = false,
            },
            StringComparer.Ordinal);
        railRoot.Controls.Add(compactSession);
        railRoot.Controls.Add(compactInspector);
        railRoot.Controls.Add(pageHost);
        foreach (var page in pages.Values)
        {
            pageHost.Controls.Add(page);
        }
        _ = host.Handle;
        _ = placementRoot.Handle;
        _ = railRoot.Handle;
        _ = permanentViewportHost.Handle;
        var originalViewportHandle = viewport.Handle;
        var originalViewportParent = viewport.Parent;

        var originalControls = sessionCommands
            .Cast<Control>()
            .Concat(editSections)
            .Concat(inspectorSections)
            .Append(morphSection)
            .Append(viewport)
            .ToArray();
        var originalIdentities = originalControls
            .ToDictionary(control => control.Name, control => control, StringComparer.Ordinal);

        foreach (var command in sessionCommands)
        {
            EditMeshLayoutContracts.MoveControl(command, compactSession, DockStyle.None);
        }
        Require(
            viewport.IsHandleCreated
                && viewport.Handle == originalViewportHandle
                && ReferenceEquals(viewport.Parent, originalViewportParent),
            "Activating the tool rail changed the permanent viewport host or handle.");
        EditMeshLayoutContracts.MoveControl(editSections[0], pages["Selection"], DockStyle.Top);
        EditMeshLayoutContracts.MoveControl(editSections[1], pages["Selection"], DockStyle.Top);
        EditMeshLayoutContracts.MoveControl(editSections[2], pages["Transform"], DockStyle.Top);
        EditMeshLayoutContracts.MoveControl(editSections[3], pages["Brush"], DockStyle.Top);
        EditMeshLayoutContracts.MoveControl(editSections[4], pages["Topology"], DockStyle.Top);
        EditMeshLayoutContracts.MoveControl(editSections[5], pages["Colour"], DockStyle.Top);
        foreach (var section in inspectorSections)
        {
            AddRow(compactInspector, section);
        }
        EditMeshLayoutContracts.MoveControl(
            morphSection,
            pages["Morph & Refit"],
            DockStyle.Top);
        railRoot.Visible = true;
        placementRoot.Visible = false;

        var pagesVisited = new List<string>();
        foreach (var selectedPage in ToolPages)
        {
            foreach (var pair in pages)
            {
                pair.Value.Visible = string.Equals(
                    pair.Key,
                    selectedPage,
                    StringComparison.Ordinal);
            }
            Require(
                pages[selectedPage].Visible,
                $"The {selectedPage} rail page was not reachable.");
            pagesVisited.Add(selectedPage);
        }

        // Leaving mesh edit: only the sections placement mode shares with the
        // rail return to the flanks, in the cells they were built in. The
        // mesh-edit-only sections keep their rail pages as their one home.
        EditMeshLayoutContracts.MoveControl(
            editSections[0],
            placementLeft,
            partPickHomeCell.Column,
            partPickHomeCell.Row,
            DockStyle.Top);
        EditMeshLayoutContracts.MoveControl(
            inspectorSections[2],
            placementRight,
            viewportSectionHomeCell.Column,
            viewportSectionHomeCell.Row,
            DockStyle.Top);
        Require(
            viewport.IsHandleCreated
                && viewport.Handle == originalViewportHandle
                && ReferenceEquals(viewport.Parent, originalViewportParent),
            "Returning to the placement flanks changed the permanent viewport host or handle.");
        railRoot.Visible = false;
        placementRoot.Visible = true;

        Require(
            originalControls.All(control =>
                originalIdentities.TryGetValue(control.Name, out var original)
                && ReferenceEquals(original, control)
                && !control.IsDisposed),
            "A live Edit Mesh control was replaced or disposed during the layout round trip.");
        Require(
            ReferenceEquals(viewport.Parent, permanentViewportHost),
            "The resident viewport region left its permanent host.");
        Require(
            ReferenceEquals(editSections[0].Parent, placementLeft)
                && placementLeft.GetCellPosition(editSections[0]) == partPickHomeCell,
            "Part Pick did not return to its placement cell.");
        Require(
            ReferenceEquals(inspectorSections[2].Parent, placementRight)
                && placementRight.GetCellPosition(inspectorSections[2]) == viewportSectionHomeCell,
            "The Viewport section did not return to its placement cell.");
        Require(
            sessionCommands.All(command => ReferenceEquals(command.Parent, compactSession)),
            "A session command left the compact session bar, which is its only home.");
        Require(
            editSections.Skip(1).All(section => ReferenceEquals(section.Parent?.Parent, pageHost))
                && ReferenceEquals(morphSection.Parent?.Parent, pageHost),
            "A mesh-edit-only section left its rail page, which is its only home.");
        Require(
            EditMeshLayoutContracts.MorphColumnsForLogicalWidth(899) == 1
                && EditMeshLayoutContracts.MorphColumnsForLogicalWidth(900) == 2
                && EditMeshLayoutContracts.MorphColumnsForLogicalWidth(1499) == 2
                && EditMeshLayoutContracts.MorphColumnsForLogicalWidth(1500) == 4,
            "Responsive Morph & Refit column thresholds changed.");
        RequireToolColumnMetrics();
        RequireToolListContract();
        RequireBrushFalloffProfile();
        var morphWizard = RequireMorphAuthorWizardContract();
        var viewportColorPreferences = RequireViewportColorPreferenceContract();
        var viewportBackdrop = RequireViewportBackdropOverrideContract();
        var overlayAppearance = RequireOverlayAppearanceContract();

        // The rail is one flat list: every armable tool is its own button, and
        // clicking one arms exactly that tool. Edit Mesh boots on "orbit", and
        // the camera is not a rail entry — it is reached by the modifiers on the
        // navigation strip — so orbit must own no page and the rail opens with
        // nothing highlighted and nothing armed.
        var openingPage = EditMeshLayoutContracts.ToolRailPageForTool("orbit");
        Require(
            openingPage is null,
            "Edit Mesh no longer opens with the rail cleared, so a tool is armed on entry.");
        Require(
            EditMeshLayoutContracts.ToolRailPageForTool(string.Empty) is null
                && EditMeshLayoutContracts.ToolRailPageForTool("not_a_tool") is null,
            "An unknown tool no longer leaves the rail cleared.");
        Require(
            Enum.GetValues<ToolRailPage>().All(
                page => !EditMeshLayoutContracts.RailPageOwnsTool(page, "orbit")),
            "A rail page claimed the orbit tool.");

        // The flat tool inventory: each rail tool resolves to the page that owns
        // it, and that page owns it back. Six tools across three modal pages.
        Require(
            EditMeshLayoutContracts.RailToolOrder.SequenceEqual(
                new[] { "select", "move", "grab", "smooth", "inflate", "pinch" }),
            "The rail's flat tool inventory changed.");
        foreach (var tool in EditMeshLayoutContracts.RailToolOrder)
        {
            var owner = EditMeshLayoutContracts.ToolRailPageForTool(tool);
            Require(
                owner is not null
                    && EditMeshLayoutContracts.RailPageOwnsTool(owner.Value, tool)
                    && EditMeshLayoutContracts.RailPageIsModal(owner.Value),
                $"The rail tool '{tool}' no longer resolves to a modal page that owns it.");
        }
        Require(
            EditMeshLayoutContracts.ToolRailPageForTool("select") == ToolRailPage.Selection
                && EditMeshLayoutContracts.ToolRailPageForTool("grab") == ToolRailPage.Transform
                && EditMeshLayoutContracts.ToolRailPageForTool("pinch") == ToolRailPage.Brush,
            "A rail tool no longer resolves to its own page.");
        Require(
            !EditMeshLayoutContracts.RailPageOwnsTool(ToolRailPage.Selection, "smooth")
                && !EditMeshLayoutContracts.RailPageOwnsTool(ToolRailPage.Brush, "select"),
            "A rail page claimed a tool that belongs to another page.");

        // Command pages arm no tool, so the viewport sits on orbit the whole
        // time one is open. Whether the rail may close a page because the tool
        // is orbit is decided by whether the page is modal at all -- closing on
        // the tool alone shut Topology, Colour and Morph & Refit every time the
        // host published a disabled mesh-edit state.
        var commandPages = Enum.GetValues<ToolRailPage>()
            .Where(page => !EditMeshLayoutContracts.RailPageIsModal(page))
            .ToArray();
        var modalPages = Enum.GetValues<ToolRailPage>()
            .Where(EditMeshLayoutContracts.RailPageIsModal)
            .ToArray();
        Require(
            commandPages.Length == 3 && modalPages.Length == 3,
            "The split between modal tool pages and command pages changed.");
        Require(
            EditMeshLayoutContracts.RailCommandPageOrder.SequenceEqual(
                new[] { ToolRailPage.Topology, ToolRailPage.Colour, ToolRailPage.MorphRefit }),
            "The rail's command-page entries changed.");
        Require(
            commandPages.Contains(ToolRailPage.Topology)
                && commandPages.Contains(ToolRailPage.Colour)
                && commandPages.Contains(ToolRailPage.MorphRefit),
            "A command page became modal, so orbit would now close it.");
        Require(
            EditMeshLayoutContracts.RailToolOrder
                .Select(tool => EditMeshLayoutContracts.ToolRailPageForTool(tool))
                .All(page => page is not null && !commandPages.Contains(page.Value)),
            "A rail tool resolved to a command page.");

        // The built rail must match the executed contract inventories.
        EditMeshLayoutContracts.RequireCompleteRail(
            EditMeshLayoutContracts.RailToolOrder,
            EditMeshLayoutContracts.RailCommandPageOrder);

        // Rebinding: every accepted modifier resolves to itself, anything else
        // falls back, and the default pair does not collide.
        Require(
            CameraModifierBindings.Normalize("ALT", CameraModifierBindings.DefaultOrbit) == CameraModifierBindings.Alt
                && CameraModifierBindings.Normalize(" shift ", CameraModifierBindings.DefaultOrbit) == CameraModifierBindings.Shift
                && CameraModifierBindings.Normalize("nonsense", CameraModifierBindings.DefaultPan) == CameraModifierBindings.DefaultPan
                && CameraModifierBindings.Normalize(null, CameraModifierBindings.DefaultOrbit) == CameraModifierBindings.DefaultOrbit,
            "Camera modifier normalization changed.");
        Require(
            CameraModifierBindings.IsHeld(CameraModifierBindings.AltOrCtrl, Keys.Alt)
                && CameraModifierBindings.IsHeld(CameraModifierBindings.AltOrCtrl, Keys.Control)
                && !CameraModifierBindings.IsHeld(CameraModifierBindings.AltOrCtrl, Keys.Shift)
                && CameraModifierBindings.IsHeld(CameraModifierBindings.Shift, Keys.Shift)
                && !CameraModifierBindings.IsHeld(CameraModifierBindings.Shift, Keys.Alt),
            "Camera modifier hit-testing changed.");
        Require(
            !CameraModifierBindings.IsHeld(CameraModifierBindings.DefaultOrbit, Keys.Shift)
                && !CameraModifierBindings.IsHeld(CameraModifierBindings.DefaultPan, Keys.Alt)
                && !CameraModifierBindings.IsHeld(CameraModifierBindings.DefaultPan, Keys.Control),
            "The default orbit and pan modifiers now collide.");

        // A prewarm-launched helper holds a placeholder nobody asked to see, and
        // must refuse to be revealed until a real package has been applied to it.
        // Every other combination activates, including a prewarmed process that
        // has since taken a real package.
        Require(
            ResidentActivationContract.ShouldDeferActivation(prewarmLaunch: true, residentPackageLoadCount: 0)
                && !ResidentActivationContract.ShouldDeferActivation(prewarmLaunch: true, residentPackageLoadCount: 1)
                && !ResidentActivationContract.ShouldDeferActivation(prewarmLaunch: false, residentPackageLoadCount: 0)
                && !ResidentActivationContract.ShouldDeferActivation(prewarmLaunch: false, residentPackageLoadCount: 3),
            "The resident activation contract would reveal the prewarm placeholder.");
        Require(
            ResidentActivationContract.MatchesAcceptedPackageGeneration(
                activationPackageGeneration: 1,
                acceptedPackageGeneration: 0)
                && ResidentActivationContract.MatchesAcceptedPackageGeneration(
                    activationPackageGeneration: 2,
                    acceptedPackageGeneration: 2)
                && !ResidentActivationContract.MatchesAcceptedPackageGeneration(
                    activationPackageGeneration: 1,
                    acceptedPackageGeneration: 2)
                && !ResidentActivationContract.MatchesAcceptedPackageGeneration(
                    activationPackageGeneration: 0,
                    acceptedPackageGeneration: 2),
            "A stale activation package generation could cross a resident replacement boundary.");
        // The signature in activate_request can be stale by the time the
        // helper requests a sync. The first accepted post-sync publication is
        // the authoritative target ("current" below), while an older
        // pre-sync completion must not consume it.
        Require(
            ResidentActivationContract.MatchesPendingMaterialSync(
                waiting: true,
                pendingGeneration: 8,
                completedGeneration: 8,
                pendingSignature: "current",
                completedSignature: "current")
                && !ResidentActivationContract.MatchesPendingMaterialSync(
                    waiting: true,
                    pendingGeneration: 8,
                    completedGeneration: 7,
                    pendingSignature: "current",
                    completedSignature: "stale-request")
                && !ResidentActivationContract.MatchesPendingMaterialSync(
                    waiting: true,
                    pendingGeneration: 8,
                    completedGeneration: 8,
                    pendingSignature: "current",
                    completedSignature: "stale"),
            "A stale material completion could consume a pending activation.");

        var report = new Dictionary<string, object?>
        {
            ["ok"] = true,
            ["defers_prewarm_placeholder_activation"] = ResidentActivationContract.ShouldDeferActivation(
                prewarmLaunch: true,
                residentPackageLoadCount: 0),
            ["material_sync_completion_is_correlated"] = true,
            ["activation_package_generation_is_fenced"] = true,
            ["tool_rail_default"] = true,
            ["tool_rail_only_layout"] = true,
            ["round_trip_layout"] = "placement",
            ["same_control_instances"] = true,
            ["same_viewport_instance"] = true,
            ["same_viewport_handle"] = true,
            ["stable_viewport_parent"] = true,
            ["pages_visited"] = pagesVisited,
            ["rail_tool_count"] = EditMeshLayoutContracts.RailToolOrder.Length,
            ["rail_command_page_count"] = EditMeshLayoutContracts.RailCommandPageOrder.Length,
            ["rail_tools"] = EditMeshLayoutContracts.RailToolOrder,
            ["opening_page"] = openingPage?.ToString() ?? "none",
            ["opening_tool"] = "orbit",
            ["camera_orbit_modifier_default"] = CameraModifierBindings.DefaultOrbit,
            ["camera_pan_modifier_default"] = CameraModifierBindings.DefaultPan,
            ["morph_columns"] = new Dictionary<string, int>
            {
                ["narrow"] = EditMeshLayoutContracts.MorphColumnsForLogicalWidth(899),
                ["medium"] = EditMeshLayoutContracts.MorphColumnsForLogicalWidth(900),
                ["wide"] = EditMeshLayoutContracts.MorphColumnsForLogicalWidth(1500),
            },
            ["morph_profile_wizard"] = morphWizard,
            ["viewport_color_preferences"] = viewportColorPreferences,
            ["viewport_backdrop_override"] = viewportBackdrop,
            ["overlay_appearance"] = overlayAppearance,
            ["tool_column_width"] = ToolColumnWidthReport(),
            ["tool_list_row_count"] = EditMeshToolListContract.RowOrder.Length,
            ["zero_size_splitter_construction"] = true,
            ["renderer_started"] = false,
            ["visible_window_started"] = false,
        };
        File.WriteAllText(
            reportPath,
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }

    /// <summary>
    /// What the dock costs in each state, so a regression that reintroduces a
    /// fixed-width column is visible in the report rather than only in a failure.
    /// </summary>
    private static Dictionary<string, int> ToolColumnWidthReport() => new()
    {
        ["collapsed"] = EditMeshToolColumnMetrics.PreferredColumnWidth(0, null),
        ["brush_open"] = EditMeshToolColumnMetrics.PreferredColumnWidth(320, ToolRailPage.Brush),
        ["morph_open"] = EditMeshToolColumnMetrics.PreferredColumnWidth(520, ToolRailPage.MorphRefit),
        ["inspector"] = EditMeshToolColumnMetrics.PreferredInspectorWidth(300),
    };

    /// <summary>
    /// The column is measured, not reserved. These are the three cases that
    /// decide whether the dock wastes width: nothing open, an ordinary page
    /// open, and the one page allowed to push past the ceiling.
    /// </summary>
    private static void RequireToolColumnMetrics()
    {
        Require(
            EditMeshToolColumnMetrics.PreferredColumnWidth(0, null)
                == EditMeshToolColumnMetrics.CollapsedFloor,
            "A closed tool column no longer collapses to the row width.");
        Require(
            EditMeshToolColumnMetrics.PreferredColumnWidth(9999, null)
                <= EditMeshToolColumnMetrics.ExpandedFloor,
            "A closed tool column grew past its own cap.");
        Require(
            EditMeshToolColumnMetrics.PreferredColumnWidth(0, ToolRailPage.Brush)
                == EditMeshToolColumnMetrics.ExpandedFloor,
            "An open page no longer gets its floor width.");
        Require(
            EditMeshToolColumnMetrics.PreferredColumnWidth(9999, ToolRailPage.Brush)
                == EditMeshToolColumnMetrics.ExpandedCeiling,
            "A capped page no longer stops at the ceiling.");
        // Morph & Refit's three-button row clips rather than wraps, so it is the
        // one page allowed past the ceiling.
        Require(
            EditMeshToolColumnMetrics.PageWidthIsUncapped(ToolRailPage.MorphRefit)
                && Enum.GetValues<ToolRailPage>()
                    .Where(page => page != ToolRailPage.MorphRefit)
                    .All(page => !EditMeshToolColumnMetrics.PageWidthIsUncapped(page)),
            "The set of pages allowed past the width ceiling changed.");
        Require(
            EditMeshToolColumnMetrics.PreferredColumnWidth(9999, ToolRailPage.MorphRefit)
                == EditMeshToolColumnMetrics.UncappedCeiling,
            "The uncapped page lost its own hard stop.");
        Require(
            EditMeshToolColumnMetrics.PreferredInspectorWidth(0)
                    == EditMeshToolColumnMetrics.InspectorFloor
                && EditMeshToolColumnMetrics.PreferredInspectorWidth(9999)
                    == EditMeshToolColumnMetrics.InspectorCeiling,
            "The scene inspector width no longer follows its own bounds.");
    }

    /// <summary>
    /// The list's rows, and the cell arithmetic that puts an open body directly
    /// under the row that opened it.
    /// </summary>
    private static void RequireToolListContract()
    {
        EditMeshToolListContract.RequireCompleteList(
            EditMeshToolListContract.RowOrder.Select(row => row.Key).ToArray());
        Require(
            EditMeshToolListContract.RowOrder.Length == 9,
            "The Edit Mesh tool list's row count changed.");
        Require(
            EditMeshToolListContract.RowForTool("orbit") is null
                && EditMeshToolListContract.RowForTool(null) is null
                && EditMeshToolListContract.RowForTool("not_a_tool") is null,
            "An unarmed or unknown tool claimed a list row.");
        Require(
            EditMeshToolListContract.RowForTool("inflate")?.Page == ToolRailPage.Brush
                && EditMeshToolListContract.RowForTool("grab")?.Page == ToolRailPage.Transform,
            "A tool row no longer opens the page that owns its tool.");
        // Six tool rows over three shared bodies is the whole point: the row is
        // the only place a tool is named, so a page cannot name it again.
        Require(
            EditMeshToolListContract.RowOrder
                .Where(row => row.Kind == ToolListRowKind.Tool)
                .Select(row => row.Page)
                .Distinct()
                .Count() == 3,
            "The tool rows no longer share three modal pages.");
        Require(
            EditMeshToolListContract.RowOrder
                .Select(row => row.Key)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Count() == EditMeshToolListContract.RowOrder.Length,
            "Two list rows carry the same key, so one names something twice.");

        // The open body sits directly under its row, and everything below it —
        // later rows and the group label alike — moves down exactly one cell.
        var groupCell = EditMeshToolListContract.GroupLabelBaseCell;
        Require(
            EditMeshToolListContract.BaseCell(groupCell) == groupCell + 1,
            "The command group label no longer owns a cell above the command rows.");
        var firstToolCell = EditMeshToolListContract.BaseCell(0);
        Require(
            EditMeshToolListContract.ResolvedCell(firstToolCell, null) == firstToolCell
                && EditMeshToolListContract.ResolvedCell(firstToolCell, firstToolCell) == firstToolCell
                && EditMeshToolListContract.ResolvedCell(firstToolCell + 1, firstToolCell)
                    == firstToolCell + 2,
            "Opening a row no longer pushes the rows below it down by one.");
        Require(
            EditMeshToolListContract.BodyCell(firstToolCell) == firstToolCell + 1,
            "The open body no longer sits directly under the row that opened it.");
        Require(
            EditMeshToolListContract.ParkedBodyCell
                == EditMeshToolListContract.TableRowCount - 1,
            "The closed body host no longer parks below every row.");
    }

    /// <summary>
    /// The falloff preview draws <c>brush_falloff_weight</c>, so these are the
    /// values native mesh core produces. A preview that drifted from the brush
    /// would quietly misreport every stroke.
    /// </summary>
    private static void RequireBrushFalloffProfile()
    {
        static bool Near(double actual, double expected) => Math.Abs(actual - expected) < 1e-9;

        Require(
            Near(BrushFalloffProfile.Weight(0.0, 24.0, BrushFalloffProfile.Smooth), 1.0)
                && Near(BrushFalloffProfile.Weight(24.0, 24.0, BrushFalloffProfile.Smooth), 0.0)
                && Near(BrushFalloffProfile.Weight(48.0, 24.0, BrushFalloffProfile.Smooth), 0.0),
            "The brush falloff profile no longer runs from full at the centre to zero at the rim.");
        // 1 - t^2(3 - 2t) at the halfway point is exactly 0.5.
        Require(
            Near(BrushFalloffProfile.Weight(12.0, 24.0, BrushFalloffProfile.Smooth), 0.5),
            "The smooth falloff is no longer the complement of smoothstep.");
        Require(
            Near(BrushFalloffProfile.Weight(6.0, 24.0, BrushFalloffProfile.Linear), 0.75)
                && Near(BrushFalloffProfile.Weight(18.0, 24.0, BrushFalloffProfile.Linear), 0.25),
            "The linear falloff is no longer 1 - t.");
        Require(
            Near(BrushFalloffProfile.Weight(12.0, 24.0, BrushFalloffProfile.Sharp), 0.25),
            "The sharp falloff is no longer (1 - t) squared.");
        Require(
            Near(BrushFalloffProfile.Weight(0.0, 24.0, BrushFalloffProfile.Constant), 1.0)
                && Near(BrushFalloffProfile.Weight(23.9, 24.0, BrushFalloffProfile.Constant), 1.0)
                && Near(BrushFalloffProfile.Weight(24.0, 24.0, BrushFalloffProfile.Constant), 0.0),
            "The constant falloff no longer holds full weight to the rim.");
        // A degenerate radius must not divide by zero.
        Require(
            Near(BrushFalloffProfile.Weight(0.0, 0.0, BrushFalloffProfile.Smooth), 1.0)
                && Near(BrushFalloffProfile.Weight(1.0, 0.0, BrushFalloffProfile.Smooth), 0.0),
            "A zero-radius brush no longer degenerates to a point.");
        // An unknown name falls through to smooth, exactly as the C++ does.
        Require(
            Near(
                BrushFalloffProfile.Weight(12.0, 24.0, "not_a_falloff"),
                BrushFalloffProfile.Weight(12.0, 24.0, BrushFalloffProfile.Smooth)),
            "An unknown falloff no longer falls back to smooth.");
    }

    private static Dictionary<string, object?> RequireMorphAuthorWizardContract()
    {
        IReadOnlyList<MorphPartChoice> parts = new[]
        {
            new MorphPartChoice(0, "Body"),
            new MorphPartChoice(2, "Sleeve"),
        };
        using var wizard = new MorphAuthorDialog(
            string.Empty,
            string.Empty,
            definition: null,
            parts,
            Array.Empty<MorphPartChoice>(),
            new Dictionary<string, object?>(),
            Color.FromArgb(23, 25, 29),
            Color.FromArgb(31, 34, 40),
            Color.FromArgb(43, 47, 55),
            Color.White,
            Color.Silver);
        _ = wizard.Handle;
        var title = RequiredControl<Label>(wizard, "MorphWizardStepTitle");
        var validation = RequiredControl<Label>(wizard, "MorphWizardValidationLabel");
        var next = RequiredControl<Button>(wizard, "MorphWizardNextButton");
        var partList = RequiredControl<CheckedListBox>(wizard, "MorphWizardPartList");
        var deformation = RequiredControl<ComboBox>(wizard, "MorphWizardDeformation");
        var axis = RequiredControl<ComboBox>(wizard, "MorphWizardAxis");
        var profileName = RequiredControl<TextBox>(wizard, "MorphWizardProfileName");
        var profileId = RequiredControl<TextBox>(wizard, "MorphWizardProfileId");
        var definitionId = RequiredControl<TextBox>(wizard, "MorphWizardDefinitionId");
        var sliderLabel = RequiredControl<TextBox>(wizard, "MorphWizardSliderLabel");
        var finish = RequiredControl<Button>(wizard, "MorphWizardFinishButton");
        var cancel = RequiredControl<Button>(wizard, "MorphWizardCancelButton");

        Require(title.Text == "1. Profile", "The Morph wizard did not open on Profile.");
        Require(profileName.Text == "My Morph Profile", "The Morph wizard lost its friendly-name default.");
        Require(wizard.ProfileId.Length > 0 && wizard.DefinitionId.Length > 0, "The Morph wizard did not generate stable IDs.");
        Require(profileId.ReadOnly && definitionId.ReadOnly, "Generated Morph IDs became user-editable again.");
        InvokeButton(next);
        Require(title.Text == "2. Parts", "Enter/Next did not advance the Morph wizard to Parts.");
        InvokeButton(next);
        Require(
            title.Text == "2. Parts" && validation.Text.Contains("at least one part", StringComparison.OrdinalIgnoreCase),
            "The Morph wizard accepted an empty part selection.");

        partList.SetItemChecked(0, true);
        Application.DoEvents();
        var selectedPartChoiceCount = partList.CheckedItems.Count;
        InvokeButton(next);
        Require(title.Text == "3. Deformation", "The Morph wizard did not advance to Deformation.");
        var advancedToggle = RequiredControl<Button>(wizard, "MorphWizardAdvancedToggle");
        var advancedBody = RequiredControl<Panel>(wizard, "MorphWizardAdvancedBody");
        var advancedMaximum = RequiredControl<NumericUpDown>(wizard, "MorphWizardMaximum");
        InvokeButton(advancedToggle);
        wizard.PerformLayout();
        Require(
            advancedBody.PreferredSize.Height > 0
                && advancedMaximum.PreferredSize.Height > 0
                && advancedMaximum.Parent is not null,
            $"The Morph wizard Advanced fields did not expand into layout bounds (body={advancedBody.PreferredSize.Height}, maximum={advancedMaximum.PreferredSize.Height}).");
        var defaults = wizard.Payload;
        Require(
            string.Equals(Convert.ToString(defaults["rule"]), "volume", StringComparison.Ordinal)
                && string.Equals(Convert.ToString(defaults["axis"]), "y", StringComparison.Ordinal)
                && Convert.ToDouble(defaults["amount"]) == 0.1
                && Convert.ToInt32(defaults["feather"]) == 2
                && string.Equals(Convert.ToString(defaults["falloff"]), "smooth", StringComparison.Ordinal)
                && string.Equals(Convert.ToString(defaults["mirror_mode"]), "off", StringComparison.Ordinal)
                && Convert.ToDouble(defaults["min_percent"]) == -100.0
                && Convert.ToDouble(defaults["max_percent"]) == 100.0,
            "The Morph wizard's established deformation defaults changed.");
        deformation.SelectedItem = "Move";
        axis.SelectedItem = "Z";
        sliderLabel.Text = "Waist Move";
        InvokeButton(next);
        Require(title.Text == "4. Preview & Save", "The Morph wizard did not advance to Preview & Save.");
        Require(ReferenceEquals(wizard.AcceptButton, finish), "Enter does not save from the final Morph wizard page.");

        var previews = new List<double>();
        wizard.PreviewRequested += (_, value) => previews.Add(value);
        InvokeButton(RequiredControl<Button>(wizard, "MorphWizardPreviewMinimum"));
        InvokeButton(RequiredControl<Button>(wizard, "MorphWizardPreviewDefault"));
        InvokeButton(RequiredControl<Button>(wizard, "MorphWizardPreviewMaximum"));
        Require(
            previews.SequenceEqual(new[] { -100.0, 0.0, 100.0 }) && wizard.PreviewWasSent,
            "The Morph wizard did not preview minimum, default, and maximum in order.");
        wizard.SetProtocolBusy(true, "Testing correlated command lock.");
        Require(
            !finish.Enabled
                && !cancel.Enabled
                && !RequiredControl<Button>(wizard, "MorphWizardPreviewMinimum").Enabled,
            "The Morph wizard can close or start another preview while a correlated command sequence is active.");
        wizard.SetProtocolBusy(false, string.Empty);
        InvokeButton(finish);
        Require(wizard.DialogResult == DialogResult.OK, "Save Profile did not finish the Morph wizard.");

        RequireExistingMorphAuthorWizardContract(parts);

        return new Dictionary<string, object?>
        {
            ["opening_page"] = "Profile",
            ["empty_selection_blocked"] = true,
            ["part_chip_count"] = selectedPartChoiceCount,
            ["advanced_visible"] = true,
            ["defaults_preserved"] = true,
            ["preview_values"] = previews,
            ["save_result"] = wizard.DialogResult.ToString(),
            ["existing_profile_reloaded"] = true,
            ["existing_profile_scope_preserved"] = true,
            ["mesh_selection_preserved"] = true,
        };
    }

    private static Dictionary<string, object?> RequireViewportBackdropOverrideContract()
    {
        // The effect dialog asks for its own backdrop, and the host has already set a
        // colour override from the reader's remembered preference. That override wins over
        // the presentation payload's quality colour, so the backdrop has to arrive as an
        // override too -- which is a thing to prove at the clear colour, not at a field.
        var document = HeadlessGpuSparseSoak.BuildSyntheticDocument(64);
        var materials = NetMaterialSet.Empty;
        using var textures = NetTextureSet.Load(materials);
        var scene = NetSceneState.Load(string.Empty, document.Submeshes.Count);
        using var viewport = new MeshViewport(document, materials, textures, scene, HeadlessGpuInteractionSoak.SyntheticLaunchOptions());
        viewport.SetViewportColorOverrides(Color.FromArgb(0x3B, 0x3B, 0x3B), null);
        var before = viewport.ResidentBackgroundColor;

        var state = new Dictionary<string, object?>
        {
            ["active_view"] = "editable",
            ["display"] = new Dictionary<string, object?> { ["viewport_background_color"] = "#101014" },
        };
        using var payload = JsonDocument.Parse(JsonSerializer.Serialize(state));
        Require(
            viewport.TryApplyPresentationState(payload.RootElement, out var error),
            $"A presentation state naming a backdrop was rejected: {error}");
        var after = viewport.ResidentBackgroundColor;
        static float ToLinear(float channel) =>
            channel <= 0.04045f ? channel / 12.92f : MathF.Pow((channel + 0.055f) / 1.055f, 2.4f);
        var expected = ToLinear(0x10 / 255.0f);
        Require(
            MathF.Abs(after.X - expected) < 0.0005f && MathF.Abs(after.Y - expected) < 0.0005f,
            $"The backdrop did not reach the clear colour: {after.X:F4} rather than {expected:F4}.");
        Require(
            MathF.Abs(after.X - before.X) > 0.0005f,
            "The clear colour did not move, so the payload changed nothing.");
        return new Dictionary<string, object?>
        {
            ["before_linear"] = MathF.Round(before.X, 5),
            ["after_linear"] = MathF.Round(after.X, 5),
            ["expected_linear"] = MathF.Round(expected, 5),
        };
    }

    private static Dictionary<string, object?> RequireViewportColorPreferenceContract()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"cdmw-mesh-viewport-colors-{Environment.ProcessId}-{Guid.NewGuid():N}.json");
        try
        {
            Require(
                MeshViewportBackgroundPreferences.Load(path) == MeshViewportBackgroundColors.Default,
                "A missing viewport-colour preference did not use renderer defaults.");
            var chosen = new MeshViewportBackgroundColors(
                Color.FromArgb(0x12, 0x34, 0x56),
                Color.FromArgb(0xAB, 0xCD, 0xEF));
            Require(
                MeshViewportBackgroundPreferences.TrySave(chosen, path, out var saveError),
                $"Viewport-colour preference save failed: {saveError}");
            Require(
                MeshViewportBackgroundPreferences.Load(path) == chosen,
                "Viewport background/grid colours did not survive reload.");

            File.WriteAllText(path, "{not json", System.Text.Encoding.UTF8);
            Require(
                MeshViewportBackgroundPreferences.Load(path) == MeshViewportBackgroundColors.Default,
                "An invalid viewport-colour file did not fall back to defaults.");
            File.WriteAllText(
                path,
                "{\"schema\":\"cdmw_mesh_viewport_background_v1\",\"background_color\":\"bad\",\"grid_color\":\"#010203\"}",
                System.Text.Encoding.UTF8);
            var partial = MeshViewportBackgroundPreferences.Load(path);
            Require(
                partial.Background == MeshViewportBackgroundColors.Default.Background
                    && partial.Grid == Color.FromArgb(1, 2, 3),
                "A bad viewport colour did not fall back without discarding its valid sibling.");

            Require(
                MeshViewportBackgroundPreferences.TrySave(
                    MeshViewportBackgroundColors.Default,
                    path,
                    out saveError),
                $"Viewport-colour reset save failed: {saveError}");
            Require(
                MeshViewportBackgroundPreferences.Load(path) == MeshViewportBackgroundColors.Default,
                "Reset viewport colours did not persist renderer defaults.");
            return new Dictionary<string, object?>
            {
                ["save_load"] = true,
                ["invalid_file_fallback"] = true,
                ["per_field_fallback"] = true,
                ["reset_persisted"] = true,
            };
        }
        finally
        {
            try
            {
                File.Delete(path);
            }
            catch
            {
                // The acceptance result already reflects the actual preference
                // contract; temp cleanup must not turn it into a false failure.
            }
        }
    }

    private static Dictionary<string, object?> RequireOverlayAppearanceContract()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            $"cdmw-mesh-overlay-{Environment.ProcessId}-{Guid.NewGuid():N}.json");
        try
        {
            Require(
                MeshOverlayPreferences.Load(path) == MeshOverlaySettings.Default,
                "A missing overlay preference did not use selection renderer defaults.");
            var chosen = new MeshOverlaySettings(
                new MeshOverlayColors(
                    Color.FromArgb(1, 2, 3),
                    Color.FromArgb(4, 5, 6),
                    Color.FromArgb(7, 8, 9),
                    Color.FromArgb(10, 11, 12)),
                new MeshOverlaySizing(2.4f, 12.5f));
            Require(
                MeshOverlayPreferences.TrySave(chosen, out var saveError, path),
                $"Overlay preference save failed: {saveError}");
            Require(
                MeshOverlayPreferences.Load(path) == chosen,
                "Committed/live selection colours or overlay sizing did not survive reload.");

            File.WriteAllText(
                path,
                "{\"schema\":\"cdmw_mesh_overlay_preferences_v2\",\"wire_color\":\"#112233\",\"vertex_color\":\"#445566\",\"wire_width_pixels\":3.5,\"vertex_marker_size_pixels\":9}",
                System.Text.Encoding.UTF8);
            var migratedV2 = MeshOverlayPreferences.Load(path);
            Require(
                migratedV2.Colors.Wire == Color.FromArgb(0x11, 0x22, 0x33)
                    && migratedV2.Colors.Vertex == Color.FromArgb(0x44, 0x55, 0x66)
                    && migratedV2.Colors.Selection == MeshOverlayColors.Default.Selection
                    && migratedV2.Colors.LiveSelection == MeshOverlayColors.Default.LiveSelection
                    && migratedV2.Sizing == new MeshOverlaySizing(3.5f, 9.0f),
                "Overlay v2 preferences did not migrate selection colours with their defaults.");

            File.WriteAllText(
                path,
                "{\"schema\":\"cdmw_mesh_overlay_colors_v1\",\"wire_color\":\"#203040\",\"vertex_color\":\"#506070\"}",
                System.Text.Encoding.UTF8);
            var migratedV1 = MeshOverlayPreferences.Load(path);
            Require(
                migratedV1.Colors.Wire == Color.FromArgb(0x20, 0x30, 0x40)
                    && migratedV1.Colors.Vertex == Color.FromArgb(0x50, 0x60, 0x70)
                    && migratedV1.Colors.Selection == MeshOverlayColors.Default.Selection
                    && migratedV1.Colors.LiveSelection == MeshOverlayColors.Default.LiveSelection
                    && migratedV1.Sizing == MeshOverlaySizing.Default,
                "Overlay v1 preferences did not preserve their legacy fields and new defaults.");

            // X-Ray draws topology through the surface, so an untouched default
            // black wire falls back to the automatic high-contrast colour. A
            // colour the reader chose is theirs in X-Ray too; overriding it is
            // what made the Preview Settings wire colour look ignored.
            var defaults = MeshOverlaySettings.Default.Colors;
            Require(
                defaults.ActiveWire(true) == MeshOverlayColors.AutomaticXRayWire
                    && defaults.ActiveVertex(true) == MeshOverlayColors.AutomaticXRayVertex,
                "An untouched overlay preference lost its automatic X-Ray colours.");
            Require(
                defaults.ActiveWire(false) == defaults.Wire
                    && defaults.ActiveVertex(false) == defaults.Vertex,
                "The automatic X-Ray colours leaked into a non-X-Ray display.");
            var picked = new MeshOverlayColors(
                Color.FromArgb(0x20, 0xC0, 0x40),
                Color.FromArgb(0xC0, 0x20, 0x40),
                MeshOverlayColors.Default.Selection,
                MeshOverlayColors.Default.LiveSelection);
            Require(
                picked.ActiveWire(true) == Color.FromArgb(0x20, 0xC0, 0x40)
                    && picked.ActiveVertex(true) == Color.FromArgb(0xC0, 0x20, 0x40),
                "X-Ray discarded the chosen wire or vertex colour for its automatic one.");

            var construction = ExperimentForm.OverlayAppearanceConstructionProof();
            Require(
                Convert.ToInt32(construction["control_count"]) == 7
                    && Math.Abs(Convert.ToSingle(construction["wire_width"]) - 2.25f) < 0.001f
                    && Math.Abs(Convert.ToSingle(construction["vertex_size"]) - 11.5f) < 0.001f
                    && string.Equals(Convert.ToString(construction["selection_color"]), "#708090", StringComparison.Ordinal)
                    && string.Equals(Convert.ToString(construction["live_selection_color"]), "#A0B0C0", StringComparison.Ordinal),
                "Viewport selection appearance controls did not construct with the configured values.");
            return new Dictionary<string, object?>
            {
                ["schema"] = MeshOverlayPreferences.Schema,
                ["save_load"] = true,
                ["v1_migration"] = true,
                ["v2_migration"] = true,
                ["xray_follows_chosen_color"] = true,
                ["xray_default_wire_color"] = MeshOverlayColors.Hex(defaults.ActiveWire(true)),
                ["xray_chosen_wire_color"] = MeshOverlayColors.Hex(picked.ActiveWire(true)),
                ["controls"] = construction,
            };
        }
        finally
        {
            try
            {
                File.Delete(path);
            }
            catch
            {
                // Temp cleanup must not replace the actual preference result.
            }
        }
    }

    private static T RequiredControl<T>(Control root, string name) where T : Control
    {
        var control = root.Controls.Find(name, searchAllChildren: true).OfType<T>().SingleOrDefault();
        return control ?? throw new InvalidOperationException($"Morph wizard control {name} is missing or duplicated.");
    }

    private static void InvokeButton(Button button)
    {
        var onClick = typeof(Button).GetMethod(
            "OnClick",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("WinForms Button.OnClick is unavailable.");
        onClick.Invoke(button, new object[] { EventArgs.Empty });
    }

    private static string RequiredValue(string[] args, string name)
    {
        var index = Array.FindIndex(
            args,
            arg => string.Equals(arg, name, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]))
        {
            throw new ArgumentException($"{name} requires an output path.");
        }
        return Path.GetFullPath(args[index + 1]);
    }

    private static TableLayoutPanel CreateStack(string name)
    {
        var stack = new TableLayoutPanel
        {
            Name = name,
            ColumnCount = 1,
            RowCount = 0,
            AutoSize = true,
        };
        stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        return stack;
    }

    private static GroupBox NewSection(string name)
    {
        return new GroupBox
        {
            Name = name.Replace(" ", string.Empty).Replace("&", string.Empty),
            Text = name,
        };
    }

    private static void AddRow(TableLayoutPanel stack, Control control)
    {
        var row = stack.RowCount;
        stack.RowCount = row + 1;
        stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        EditMeshLayoutContracts.MoveControl(control, stack, 0, row, DockStyle.Top);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
