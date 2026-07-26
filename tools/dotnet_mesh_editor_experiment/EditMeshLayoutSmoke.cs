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
        using var classicRoot = new Panel { Name = "ClassicTools", Dock = DockStyle.Fill };
        using var compactRoot = new Panel
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
        host.Controls.Add(classicRoot);
        host.Controls.Add(compactRoot);

        var classicLeft = CreateStack("ClassicLeftStack");
        var classicRight = CreateStack("ClassicRightStack");
        classicRoot.Controls.Add(classicLeft);
        classicRoot.Controls.Add(classicRight);

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
        foreach (var command in sessionCommands)
        {
            AddRow(classicLeft, command);
        }
        foreach (var section in editSections)
        {
            AddRow(classicLeft, section);
        }
        AddRow(classicRight, inspectorSections[1]);
        AddRow(classicRight, morphSection);
        AddRow(classicRight, inspectorSections[0]);
        AddRow(classicRight, inspectorSections[2]);
        permanentViewportHost.Controls.Add(viewport);

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
        compactRoot.Controls.Add(compactSession);
        compactRoot.Controls.Add(compactInspector);
        compactRoot.Controls.Add(pageHost);
        foreach (var page in pages.Values)
        {
            pageHost.Controls.Add(page);
        }
        _ = host.Handle;
        _ = classicRoot.Handle;
        _ = compactRoot.Handle;
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
            "Activating the Bottom Tool Deck changed the permanent viewport host or handle.");
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
        compactRoot.Visible = true;
        classicRoot.Visible = false;

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
                $"The {selectedPage} compact page was not reachable.");
            pagesVisited.Add(selectedPage);
        }

        ResetStack(classicLeft);
        ResetStack(classicRight);
        foreach (var command in sessionCommands)
        {
            AddRow(classicLeft, command);
        }
        foreach (var section in editSections)
        {
            AddRow(classicLeft, section);
        }
        AddRow(classicRight, inspectorSections[1]);
        AddRow(classicRight, morphSection);
        AddRow(classicRight, inspectorSections[0]);
        AddRow(classicRight, inspectorSections[2]);
        Require(
            viewport.IsHandleCreated
                && viewport.Handle == originalViewportHandle
                && ReferenceEquals(viewport.Parent, originalViewportParent),
            "Returning to Classic changed the permanent viewport host or handle.");
        compactRoot.Visible = false;
        classicRoot.Visible = true;

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
            sessionCommands.All(command => ReferenceEquals(command.Parent, classicLeft)),
            "A session command did not return to the Classic layout.");
        Require(
            editSections.All(section => ReferenceEquals(section.Parent, classicLeft)),
            "An Edit Mesh tool section did not return to the Classic left stack.");
        Require(
            inspectorSections.All(section => ReferenceEquals(section.Parent, classicRight))
                && ReferenceEquals(morphSection.Parent, classicRight),
            "An inspector or Morph & Refit section did not return to the Classic right stack.");
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

        var report = new Dictionary<string, object?>
        {
            ["ok"] = true,
            ["tool_rail_default"] = true,
            ["round_trip_layout"] = "classic",
            ["same_control_instances"] = true,
            ["same_viewport_instance"] = true,
            ["same_viewport_handle"] = true,
            ["stable_viewport_parent"] = true,
            ["pages_visited"] = pagesVisited,
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

    private static void ResetStack(TableLayoutPanel stack)
    {
        stack.Controls.Clear();
        stack.RowStyles.Clear();
        stack.RowCount = 0;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
