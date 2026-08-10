using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private Control OverlayAppearanceControls()
    {
        _wireColorButton = OverlayColorButton("Wire", "wire");
        _vertexColorButton = OverlayColorButton("Vertices", "vertex");
        _selectionColorButton = OverlayColorButton("Selected", "selection");
        _liveSelectionColorButton = OverlayColorButton("Live", "live_selection");
        ConfigureOverlaySizingControls(_wireOverlayWidth, _vertexMarkerSize, _overlaySettings);
        _wireOverlayWidth.ValueChanged += (_, _) => ApplyOverlaySizing(
            $"Wire width set to {_wireOverlayWidth.Value:0.##} px.");
        _vertexMarkerSize.ValueChanged += (_, _) => ApplyOverlaySizing(
            $"Vertex size set to {_vertexMarkerSize.Value:0.#} px.");
        var reset = StyledActionButton("Reset", ResetOverlayAppearance);
        reset.Name = "OverlayAppearanceResetButton";
        return BuildOverlayAppearanceLayout(
            _wireColorButton,
            _vertexColorButton,
            _selectionColorButton,
            _liveSelectionColorButton,
            reset,
            _wireOverlayWidth,
            _vertexMarkerSize);
    }

    private static void ConfigureOverlaySizingControls(
        NumericUpDown wireWidth,
        NumericUpDown vertexSize,
        MeshOverlaySettings settings)
    {
        ConfigureNumeric(
            wireWidth,
            decimalPlaces: 2,
            minimum: (decimal)MeshOverlaySizing.MinimumWireWidthPixels,
            maximum: (decimal)MeshOverlaySizing.MaximumWireWidthPixels,
            value: (decimal)settings.Sizing.WireWidthPixels,
            increment: 0.05M);
        ConfigureNumeric(
            vertexSize,
            decimalPlaces: 1,
            minimum: (decimal)MeshOverlaySizing.MinimumVertexMarkerSizePixels,
            maximum: (decimal)MeshOverlaySizing.MaximumVertexMarkerSizePixels,
            value: (decimal)settings.Sizing.VertexMarkerSizePixels,
            increment: 0.5M);
        wireWidth.Name = "WireOverlayWidthControl";
        wireWidth.AccessibleName = "Wire width in pixels";
        vertexSize.Name = "VertexMarkerSizeControl";
        vertexSize.AccessibleName = "Vertex size in pixels";
    }

    private static Control BuildOverlayAppearanceLayout(
        Button wire,
        Button vertex,
        Button selection,
        Button liveSelection,
        Button reset,
        NumericUpDown wireWidth,
        NumericUpDown vertexSize)
    {
        // Each of these rows owns the section's full width. Nesting them under a
        // shared "Topology appearance" label pushed the sizing row past the
        // inspector edge, which clipped the vertex-size control out of reach.
        // The two sizes share a row: a row each pushed the presets below the fold.
        return StackControls(
            ButtonRow(wire, vertex),
            ButtonRow(selection, liveSelection, reset),
            ButtonRow(
                LabeledControl("Wire px", wireWidth),
                LabeledControl("Vertex px", vertexSize)));
    }

    private Button OverlayColorButton(string label, string role) =>
        CreateOverlayColorButton(
            label,
            role,
            OverlayColorForRole(role),
            (_, _) => ChooseOverlayColor(label, role));

    private static Button CreateOverlayColorButton(
        string label,
        string role,
        Color color,
        EventHandler onClick)
    {
        var button = StyledButton(label);
        button.AutoSize = false;
        button.Height = 40;
        button.MinimumSize = new Size(0, 40);
        button.Padding = new Padding(2, 0, 2, 0);
        button.Font = new Font(button.Font.FontFamily, 8f);
        button.Name = role switch
        {
            "wire" => "WireOverlayColorButton",
            "vertex" => "VertexOverlayColorButton",
            "selection" => "CommittedSelectionColorButton",
            _ => "LiveSelectionColorButton",
        };
        button.AccessibleName = role switch
        {
            "wire" => "Wire overlay color",
            "vertex" => "Vertex overlay color",
            "selection" => "Committed selection color",
            _ => "Live selection color",
        };
        button.Click += onClick;
        ApplyOverlayColorButtonStyle(
            button,
            label,
            color);
        return button;
    }

    internal static Dictionary<string, object?> OverlayAppearanceConstructionProof()
    {
        var settings = new MeshOverlaySettings(
            new MeshOverlayColors(
                Color.FromArgb(0x10, 0x20, 0x30),
                Color.FromArgb(0x40, 0x50, 0x60),
                Color.FromArgb(0x70, 0x80, 0x90),
                Color.FromArgb(0xA0, 0xB0, 0xC0)),
            new MeshOverlaySizing(2.25f, 11.5f));
        var wireWidth = new NumericUpDown();
        var vertexSize = new NumericUpDown();
        ConfigureOverlaySizingControls(wireWidth, vertexSize, settings);
        var wire = CreateOverlayColorButton("Wire", "wire", settings.Colors.Wire, (_, _) => { });
        var vertex = CreateOverlayColorButton("Vertices", "vertex", settings.Colors.Vertex, (_, _) => { });
        var selection = CreateOverlayColorButton("Selected", "selection", settings.Colors.Selection, (_, _) => { });
        var liveSelection = CreateOverlayColorButton("Live", "live_selection", settings.Colors.LiveSelection, (_, _) => { });
        var reset = StyledActionButton("Reset", () => { });
        reset.Name = "OverlayAppearanceResetButton";
        using var root = BuildOverlayAppearanceLayout(
            wire,
            vertex,
            selection,
            liveSelection,
            reset,
            wireWidth,
            vertexSize);
        _ = root.Handle;
        var requiredNames = new[]
        {
            "WireOverlayColorButton",
            "VertexOverlayColorButton",
            "CommittedSelectionColorButton",
            "LiveSelectionColorButton",
            "OverlayAppearanceResetButton",
            "WireOverlayWidthControl",
            "VertexMarkerSizeControl",
        };
        if (requiredNames.Any(name => root.Controls.Find(name, searchAllChildren: true).Length != 1))
        {
            throw new InvalidOperationException("Viewport selection appearance controls are missing or duplicated.");
        }
        var labels = Descendants(root).OfType<Label>().Select(item => item.Text).ToArray();
        if (!labels.Contains("Wire px", StringComparer.Ordinal)
            || !labels.Contains("Vertex px", StringComparer.Ordinal))
        {
            throw new InvalidOperationException("Viewport selection appearance sizing labels were not constructed.");
        }
        return new Dictionary<string, object?>
        {
            ["control_count"] = requiredNames.Length,
            ["wire_width"] = (float)wireWidth.Value,
            ["vertex_size"] = (float)vertexSize.Value,
            ["selection_color"] = MeshOverlayColors.Hex(selection.BackColor),
            ["live_selection_color"] = MeshOverlayColors.Hex(liveSelection.BackColor),
        };

        static IEnumerable<Control> Descendants(Control parent)
        {
            foreach (Control child in parent.Controls)
            {
                yield return child;
                foreach (var descendant in Descendants(child))
                {
                    yield return descendant;
                }
            }
        }
    }

    /// <summary>
    /// The viewport's own clear colour and grid colour, picked where they are
    /// seen. They are not part of the topology overlay, so they get their own
    /// row and their own preference file, but they use the same swatch button.
    /// </summary>
    private Control ViewportColorControls()
    {
        _backgroundColorButton = ViewportColorButton("Background", background: true);
        _gridColorButton = ViewportColorButton("Grid", background: false);
        var reset = StyledActionButton("Reset", ResetViewportColors);
        reset.Name = "ViewportColorResetButton";
        return ButtonRow(_backgroundColorButton, _gridColorButton, reset);
    }

    private Button ViewportColorButton(string label, bool background)
    {
        var button = StyledButton(label);
        button.AutoSize = false;
        button.Height = 40;
        button.MinimumSize = new Size(0, 40);
        button.Padding = new Padding(2, 0, 2, 0);
        button.Font = new Font(button.Font.FontFamily, 8f);
        button.Name = background ? "ViewportBackgroundColorButton" : "ViewportGridColorButton";
        button.AccessibleName = background ? "Viewport background color" : "Viewport grid color";
        button.Click += (_, _) => ChooseViewportColor(label, background);
        ApplyOverlayColorButtonStyle(
            button,
            label,
            background ? _viewportColors.Background : _viewportColors.Grid);
        return button;
    }

    private void ChooseViewportColor(string label, bool background)
    {
        var current = background ? _viewportColors.Background : _viewportColors.Grid;
        using var dialog = new ColorDialog
        {
            Color = current,
            AllowFullOpen = true,
            AnyColor = true,
            FullOpen = true,
            SolidColorOnly = true,
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        _viewportColors = background
            ? _viewportColors with { Background = dialog.Color }
            : _viewportColors with { Grid = dialog.Color };
        ApplyViewportColors($"{label} color set to {MeshOverlayColors.Hex(dialog.Color)}.");
    }

    private void ResetViewportColors()
    {
        _viewportColors = MeshViewportBackgroundColors.Default;
        ApplyViewportColors("Viewport background and grid colors reset.");
    }

    private void ApplyViewportColors(string status)
    {
        _viewportColors = _viewportColors.Normalized();
        _viewport.SetViewportColorOverrides(_viewportColors.Background, _viewportColors.Grid);
        if (_backgroundColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_backgroundColorButton, "Background", _viewportColors.Background);
        }
        if (_gridColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_gridColorButton, "Grid", _viewportColors.Grid);
        }
        _statusLabel.Text = MeshViewportBackgroundPreferences.TrySave(_viewportColors, out var error)
            ? status
            : $"{status} Preference save failed: {error}";
    }

    private Color OverlayColorForRole(string role) => role switch
    {
        "wire" => _overlaySettings.Colors.Wire,
        "vertex" => _overlaySettings.Colors.Vertex,
        "selection" => _overlaySettings.Colors.Selection,
        _ => _overlaySettings.Colors.LiveSelection,
    };

    private void ChooseOverlayColor(string label, string role)
    {
        var current = OverlayColorForRole(role);
        using var dialog = new ColorDialog
        {
            Color = current,
            AllowFullOpen = true,
            AnyColor = true,
            FullOpen = true,
            SolidColorOnly = true,
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        var colors = role switch
        {
            "wire" => _overlaySettings.Colors with { Wire = dialog.Color },
            "vertex" => _overlaySettings.Colors with { Vertex = dialog.Color },
            "selection" => _overlaySettings.Colors with { Selection = dialog.Color },
            _ => _overlaySettings.Colors with { LiveSelection = dialog.Color },
        };
        _overlaySettings = _overlaySettings with { Colors = colors };
        // A colour picked here outranks Preview Settings for the rest of the
        // session. Without the pin, the host republishes its presentation payload
        // after every accepted frame and this choice would last one frame.
        _viewport.PinOverlayColorsFromReader();
        ApplyOverlaySettings($"{label} color set to {MeshOverlayColors.Hex(dialog.Color)}.");
    }

    private void ApplyOverlaySizing(string status)
    {
        if (_syncingOverlayAppearanceControls)
        {
            return;
        }
        _overlaySettings = _overlaySettings with
        {
            Sizing = new MeshOverlaySizing(
                (float)_wireOverlayWidth.Value,
                (float)_vertexMarkerSize.Value),
        };
        ApplyOverlaySettings(status);
    }

    private void ResetOverlayAppearance()
    {
        _overlaySettings = MeshOverlaySettings.Default;
        _viewport.PinOverlayColorsFromReader();
        ApplyOverlaySettings("Viewport selection appearance reset to the default topology, selected, and live colors.");
    }

    private void ApplyOverlaySettings(string status)
    {
        _overlaySettings = _overlaySettings.Normalized();
        _viewport.SetOverlaySettings(_overlaySettings);
        if (_wireColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_wireColorButton, "Wire", _overlaySettings.Colors.Wire);
        }
        if (_vertexColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_vertexColorButton, "Vertices", _overlaySettings.Colors.Vertex);
        }
        if (_selectionColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_selectionColorButton, "Selected", _overlaySettings.Colors.Selection);
        }
        if (_liveSelectionColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_liveSelectionColorButton, "Live", _overlaySettings.Colors.LiveSelection);
        }
        _syncingOverlayAppearanceControls = true;
        try
        {
            _wireOverlayWidth.Value = (decimal)_overlaySettings.Sizing.WireWidthPixels;
            _vertexMarkerSize.Value = (decimal)_overlaySettings.Sizing.VertexMarkerSizePixels;
        }
        finally
        {
            _syncingOverlayAppearanceControls = false;
        }
        _statusLabel.Text = MeshOverlayPreferences.TrySave(_overlaySettings, out var error)
            ? status
            : $"{status} Preference save failed: {error}";
    }

    private static void ApplyOverlayColorButtonStyle(Button button, string label, Color color)
    {
        var normalized = Color.FromArgb(color.R, color.G, color.B);
        var lightText = RelativeLuminance(normalized) < 0.44;
        button.Text = $"{label}\n{MeshOverlayColors.Hex(normalized)}";
        button.BackColor = normalized;
        button.ForeColor = lightText ? Color.White : Color.Black;
        button.FlatAppearance.MouseOverBackColor = BlendColor(normalized, Color.White, 0.16f);
        button.FlatAppearance.MouseDownBackColor = BlendColor(normalized, Color.Black, 0.16f);
        button.Height = 42;
        button.MinimumSize = new Size(0, 42);
        button.Invalidate();
    }

    private static double RelativeLuminance(Color color)
    {
        static double Channel(byte value)
        {
            var normalized = value / 255.0;
            return normalized <= 0.04045
                ? normalized / 12.92
                : Math.Pow((normalized + 0.055) / 1.055, 2.4);
        }
        return (0.2126 * Channel(color.R)) + (0.7152 * Channel(color.G)) + (0.0722 * Channel(color.B));
    }

    private static Color BlendColor(Color from, Color to, float amount)
    {
        var weight = Math.Clamp(amount, 0.0f, 1.0f);
        return Color.FromArgb(
            (int)MathF.Round(from.R + ((to.R - from.R) * weight)),
            (int)MathF.Round(from.G + ((to.G - from.G) * weight)),
            (int)MathF.Round(from.B + ((to.B - from.B) * weight)));
    }
}
