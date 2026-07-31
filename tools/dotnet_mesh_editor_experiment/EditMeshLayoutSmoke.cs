using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class EditMeshLayoutSmoke
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

        // The construction cells of the sections placement mode shares with the
        // rail: leaving mesh edit puts them back in exactly these cells.
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

        // Entering mesh edit: the session commands live on the compact bar and
        // every tool and command section moves into its rail page. This is the
        // only Edit Mesh layout.
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
        Require(
            EditMeshLayoutContracts.DefaultInspectorWidth(1180) == 380
                && EditMeshLayoutContracts.DefaultToolRailPanelWidth(1180, 68) == 448,
            "The tool rail default proportions changed.");

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

        var report = new Dictionary<string, object?>
        {
            ["ok"] = true,
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
            ["default_1180x760"] = new Dictionary<string, int>
            {
                ["inspector_width"] = EditMeshLayoutContracts.DefaultInspectorWidth(1180),
                ["tool_rail_dock_width"] =
                    EditMeshLayoutContracts.DefaultToolRailPanelWidth(1180, 68),
            },
            ["zero_size_splitter_construction"] = true,
            ["renderer_started"] = false,
            ["visible_window_started"] = false,
        };
        File.WriteAllText(
            reportPath,
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
        return 0;
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
