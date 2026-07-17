using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private readonly Dictionary<string, Button> _gizmoColorButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly NumericUpDown _gizmoLineThickness = new();
    private readonly NumericUpDown _gizmoScale = new();
    private readonly NumericUpDown _gizmoLabelSize = new();
    private readonly NumericUpDown _gizmoHandleSize = new();
    private GizmoAppearance _gizmoAppearance = GizmoAppearancePreferences.Load();
    private bool _synchronizingGizmoAppearanceControls;

    private Control GizmoAppearanceControls()
    {
        ConfigureNumeric(
            _gizmoScale,
            decimalPlaces: 2,
            minimum: (decimal)GizmoAppearance.MinimumSizeScale,
            maximum: (decimal)GizmoAppearance.MaximumSizeScale,
            value: (decimal)_gizmoAppearance.SizeScale,
            increment: 0.05M);
        ConfigureNumeric(
            _gizmoLineThickness,
            decimalPlaces: 2,
            minimum: (decimal)GizmoAppearance.MinimumLineThicknessPixels,
            maximum: (decimal)GizmoAppearance.MaximumLineThicknessPixels,
            value: (decimal)_gizmoAppearance.LineThicknessPixels,
            increment: 0.25M);
        ConfigureNumeric(
            _gizmoLabelSize,
            decimalPlaces: 0,
            minimum: (decimal)GizmoAppearance.MinimumLabelSizePixels,
            maximum: (decimal)GizmoAppearance.MaximumLabelSizePixels,
            value: (decimal)_gizmoAppearance.LabelSizePixels,
            increment: 1M);
        ConfigureNumeric(
            _gizmoHandleSize,
            decimalPlaces: 0,
            minimum: (decimal)GizmoAppearance.MinimumHandleSizePixels,
            maximum: (decimal)GizmoAppearance.MaximumHandleSizePixels,
            value: (decimal)_gizmoAppearance.HandleSizePixels,
            increment: 1M);
        _gizmoColorButtons.Clear();
        var xAxis = GizmoColorButton("X", "x");
        var yAxis = GizmoColorButton("Y", "y");
        var zAxis = GizmoColorButton("Z", "z");
        var highlight = GizmoColorButton("Active", "highlight");
        var label = GizmoColorButton("Labels", "label");
        var reset = StyledActionButton("Reset", ResetGizmoAppearance);
        _gizmoScale.ValueChanged += (_, _) => ApplyGizmoAppearanceFromControls();
        _gizmoLineThickness.ValueChanged += (_, _) => ApplyGizmoAppearanceFromControls();
        _gizmoLabelSize.ValueChanged += (_, _) => ApplyGizmoAppearanceFromControls();
        _gizmoHandleSize.ValueChanged += (_, _) => ApplyGizmoAppearanceFromControls();
        var note = new Label
        {
            Name = "GizmoAppearancePersistenceHint",
            Text = "Changes apply immediately and are saved for the next Mesh Editor session.",
            AutoSize = true,
            MaximumSize = new Size(248, 0),
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 6),
        };
        return LabeledControl(
            "Gizmo appearance",
            StackControls(
                LabeledControl("Axis colors", ButtonRow(xAxis, yAxis, zAxis)),
                LabeledControl("Feedback and labels", ButtonRow(highlight, label, reset)),
                ButtonRow(
                    LabeledControl("Gizmo size (x)", _gizmoScale),
                    LabeledControl("Line width (px)", _gizmoLineThickness)),
                ButtonRow(
                    LabeledControl("Font size (px)", _gizmoLabelSize),
                    LabeledControl("Handle size (px)", _gizmoHandleSize)),
                note));
    }

    private Button GizmoColorButton(string label, string role)
    {
        var button = StyledButton(label);
        _gizmoColorButtons[role] = button;
        button.Click += (_, _) => ChooseGizmoColor(label, role);
        ApplyOverlayColorButtonStyle(button, label, GizmoColor(role));
        return button;
    }

    private void ChooseGizmoColor(string label, string role)
    {
        using var dialog = new ColorDialog
        {
            Color = GizmoColor(role),
            AllowFullOpen = true,
            AnyColor = true,
            FullOpen = true,
            SolidColorOnly = true,
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        _gizmoAppearance = role switch
        {
            "x" => _gizmoAppearance with { XAxis = dialog.Color },
            "y" => _gizmoAppearance with { YAxis = dialog.Color },
            "z" => _gizmoAppearance with { ZAxis = dialog.Color },
            "highlight" => _gizmoAppearance with { Highlight = dialog.Color },
            _ => _gizmoAppearance with { Label = dialog.Color },
        };
        ApplyGizmoAppearance($"{label} gizmo color set to {GizmoAppearance.Hex(dialog.Color)}.");
    }

    private Color GizmoColor(string role) => role switch
    {
        "x" => _gizmoAppearance.XAxis,
        "y" => _gizmoAppearance.YAxis,
        "z" => _gizmoAppearance.ZAxis,
        "highlight" => _gizmoAppearance.Highlight,
        _ => _gizmoAppearance.Label,
    };

    private void ApplyGizmoAppearanceFromControls()
    {
        if (_synchronizingGizmoAppearanceControls)
        {
            return;
        }
        _gizmoAppearance = _gizmoAppearance with
        {
            SizeScale = (float)_gizmoScale.Value,
            LineThicknessPixels = (float)_gizmoLineThickness.Value,
            LabelSizePixels = (float)_gizmoLabelSize.Value,
            HandleSizePixels = (float)_gizmoHandleSize.Value,
        };
        ApplyGizmoAppearance("Gizmo appearance updated and saved.");
    }

    private void ResetGizmoAppearance()
    {
        _gizmoAppearance = GizmoAppearance.Default;
        SynchronizeGizmoAppearanceControls();
        ApplyGizmoAppearance("Gizmo appearance reset to defaults.");
    }

    private void SynchronizeGizmoAppearanceControls()
    {
        _synchronizingGizmoAppearanceControls = true;
        try
        {
            _gizmoScale.Value = (decimal)_gizmoAppearance.SizeScale;
            _gizmoLineThickness.Value = (decimal)_gizmoAppearance.LineThicknessPixels;
            _gizmoLabelSize.Value = (decimal)_gizmoAppearance.LabelSizePixels;
            _gizmoHandleSize.Value = (decimal)_gizmoAppearance.HandleSizePixels;
        }
        finally
        {
            _synchronizingGizmoAppearanceControls = false;
        }
    }

    private void ApplyGizmoAppearance(string status)
    {
        _gizmoAppearance = _gizmoAppearance.Normalized();
        _viewport.SetGizmoAppearance(_gizmoAppearance);
        foreach (var pair in _gizmoColorButtons)
        {
            var label = pair.Key switch
            {
                "x" => "X",
                "y" => "Y",
                "z" => "Z",
                "highlight" => "Active",
                _ => "Labels",
            };
            ApplyOverlayColorButtonStyle(pair.Value, label, GizmoColor(pair.Key));
        }
        _statusLabel.Text = GizmoAppearancePreferences.TrySave(_gizmoAppearance, out var error)
            ? status
            : $"{status} Preference save failed: {error}";
    }
}
