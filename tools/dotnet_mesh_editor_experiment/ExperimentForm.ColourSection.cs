using System.Globalization;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The Edit Mesh Colour tool page: per-part tint, recolour and glow.
///
/// Python remains the authority for every value here. This section applies the
/// edit locally so the viewport responds while the pointer is still down, then
/// publishes one latest-wins <c>part_material_edit_request</c>; the exact
/// result arrives back over the ordinary material parameter lane.
/// </summary>
internal sealed partial class ExperimentForm
{
    // Recolour strength is a slider, so a drag would otherwise emit one
    // authority request per pixel. One pending request at ~30 Hz matches the
    // placement transform lane.
    private const int PartColourAuthorityIntervalMs = 33;

    private GroupBox? _colourSection;
    private Button? _partTintButton;
    private Button? _partRecolourButton;
    private TrackBar? _partRecolourStrength;
    private Label? _partRecolourStrengthValue;
    private CheckBox? _partEmissiveCheck;
    private Button? _partEmissiveButton;
    private NumericUpDown? _partEmissiveStrength;
    private Button? _partColourResetButton;
    private Label? _partColourStatus;
    private System.Windows.Forms.Timer? _partColourAuthorityTimer;
    private Dictionary<string, object?>? _pendingPartColourEdit;
    private bool _loadingPartColourControls;
    // One texture request per page visit: the host answers asynchronously, so
    // re-asking on every refresh would spam the resident material lane.
    private bool _colourDisplayModeRequested;

    private static readonly Color NeutralPartColour = Color.White;

    // The chosen colour, kept apart from BackColor so a disabled swatch can be
    // dimmed and then restored without losing what the user picked.
    private readonly Dictionary<Button, Color> _partSwatchColours = new();

    private GroupBox BuildColourSection(TableLayoutPanel stack)
    {
        BuildColourSwatchButtons();
        BuildRecolourStrengthControls();
        BuildEmissiveControls();
        _partColourResetButton = StyledButton("Reset Colour");
        _partColourResetButton.Name = "DotNetMeshEditorPartColourResetButton";
        _partColourResetButton.Click += (_, _) => QueuePartColourEdit(
            new Dictionary<string, object?> { ["reset"] = true });
        _partColourStatus = new Label
        {
            Name = "DotNetMeshEditorPartColourStatus",
            AutoSize = true,
            MaximumSize = new Size(ScaleToolPanelWidth(ToolPropertyWidth - 40), 0),
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Text = string.Empty,
        };

        var section = AddHelpSection(
            stack,
            "Colour",
            "Recolours the selected parts. Tint multiplies the existing texture, so it can only "
            + "darken or shift it. Recolour repaints toward the chosen colour while keeping the "
            + "texture's light and shade, so a dark part can become a bright one. The preview is "
            + "approximate on metal parts; the built texture uses the exact value.",
            out _,
            ButtonRow(_partTintButton!, _partRecolourButton!),
            LabeledControl("Repaint", _partRecolourStrength!),
            _partRecolourStrengthValue!,
            _partEmissiveCheck!,
            ButtonRow(_partEmissiveButton!, _partEmissiveStrength!),
            ButtonRow(_partColourResetButton),
            _partColourStatus);
        section.Name = "CompactColourSection";
        _colourSection = section;
        _meshEditOnlySections.Add(section);
        SetPartColourSwatch(_partTintButton, NeutralPartColour);
        SetPartColourSwatch(_partRecolourButton, NeutralPartColour);
        SetPartColourSwatch(_partEmissiveButton, NeutralPartColour);
        return section;
    }

    private void BuildColourSwatchButtons()
    {
        _partTintButton = StyledButton("Tint...");
        _partTintButton.Name = "DotNetMeshEditorPartTintButton";
        _partTintButton.Click += (_, _) => PickPartColour(
            _partTintButton,
            "Choose Part Tint",
            rgb => QueuePartColourEdit(new Dictionary<string, object?>
            {
                ["tint_rgb"] = new[] { (int)rgb.R, (int)rgb.G, (int)rgb.B },
            }));

        _partRecolourButton = StyledButton("Recolour...");
        _partRecolourButton.Name = "DotNetMeshEditorPartRecolourButton";
        _partRecolourButton.Click += (_, _) => PickPartColour(
            _partRecolourButton,
            "Choose Part Colour",
            rgb =>
            {
                // Picking a colour at zero strength would look like a dead
                // control, so seed a full repaint the user can dial back.
                if (_partRecolourStrength is { Value: 0 })
                {
                    _partRecolourStrength.Value = 100;
                }
                QueuePartColourEdit(new Dictionary<string, object?>
                {
                    ["colourise_rgb"] = new[] { (int)rgb.R, (int)rgb.G, (int)rgb.B },
                    ["colourise_strength"] = PartRecolourStrengthFraction(),
                    ["colourise_authored"] = true,
                });
            });
    }

    private void BuildRecolourStrengthControls()
    {
        _partRecolourStrength = new TrackBar
        {
            Name = "DotNetMeshEditorPartRecolourStrength",
            Minimum = 0,
            Maximum = 100,
            TickFrequency = 25,
            SmallChange = 1,
            LargeChange = 10,
            AutoSize = false,
            Height = 32,
            Dock = DockStyle.Fill,
            BackColor = ThemeSectionBackground,
        };
        _partRecolourStrength.ValueChanged += (_, _) =>
        {
            UpdateRecolourStrengthLabel();
            QueuePartColourEdit(new Dictionary<string, object?>
            {
                ["colourise_rgb"] = PartColourBytes(_partRecolourButton),
                ["colourise_strength"] = PartRecolourStrengthFraction(),
                ["colourise_authored"] = true,
            });
        };
        // Releasing the slider publishes the exact landed value immediately
        // rather than waiting out the pacing interval.
        _partRecolourStrength.MouseUp += (_, _) => FlushPartColourEdit();
        _partRecolourStrength.KeyUp += (_, _) => FlushPartColourEdit();
        _partRecolourStrengthValue = new Label
        {
            Name = "DotNetMeshEditorPartRecolourStrengthValue",
            Text = "0%",
            AutoSize = true,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
        };
    }

    private void BuildEmissiveControls()
    {
        _partEmissiveCheck = new CheckBox
        {
            Name = "DotNetMeshEditorPartEmissiveCheck",
            Text = "Emits light",
            AutoSize = true,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
        };
        _partEmissiveCheck.CheckedChanged += (_, _) =>
        {
            RefreshPartColourControlsEnabled();
            QueuePartColourEdit(new Dictionary<string, object?>
            {
                ["emissive"] = _partEmissiveCheck.Checked,
            });
        };

        _partEmissiveButton = StyledButton("Glow...");
        _partEmissiveButton.Name = "DotNetMeshEditorPartEmissiveButton";
        _partEmissiveButton.Click += (_, _) => PickPartColour(
            _partEmissiveButton,
            "Choose Glow Colour",
            rgb => QueuePartColourEdit(new Dictionary<string, object?>
            {
                ["emissive"] = true,
                ["emissive_rgb"] = new[] { (int)rgb.R, (int)rgb.G, (int)rgb.B },
            }));

        _partEmissiveStrength = new NumericUpDown
        {
            Name = "DotNetMeshEditorPartEmissiveStrength",
            Dock = DockStyle.Fill,
        };
        ConfigureNumeric(
            _partEmissiveStrength,
            decimalPlaces: 2,
            minimum: 0m,
            maximum: 20m,
            value: 1m,
            increment: 0.1m);
        _partEmissiveStrength.ValueChanged += (_, _) => QueuePartColourEdit(
            new Dictionary<string, object?>
            {
                ["emissive"] = true,
                ["emissive_strength"] = (float)_partEmissiveStrength.Value,
            });
    }

    private float PartRecolourStrengthFraction() =>
        _partRecolourStrength is null ? 0f : _partRecolourStrength.Value / 100f;

    private void UpdateRecolourStrengthLabel()
    {
        if (_partRecolourStrengthValue is null || _partRecolourStrength is null)
        {
            return;
        }
        _partRecolourStrengthValue.Text = string.Format(
            CultureInfo.InvariantCulture,
            "{0}%",
            _partRecolourStrength.Value);
    }

    private static int[] PartColourBytes(Button? button)
    {
        var colour = button?.BackColor ?? NeutralPartColour;
        return new[] { (int)colour.R, (int)colour.G, (int)colour.B };
    }

    private void SetPartColourSwatch(Button? button, Color colour)
    {
        if (button is null)
        {
            return;
        }
        _partSwatchColours[button] = colour;
        // An explicit BackColor survives Enabled = false, so a disabled swatch
        // would keep inviting clicks. Blend it toward the panel to read as off.
        var painted = button.Enabled ? colour : BlendTowardPanel(colour);
        button.BackColor = painted;
        // Keep the caption legible against whatever colour was chosen.
        var luminance = ((0.299 * painted.R) + (0.587 * painted.G) + (0.114 * painted.B)) / 255.0;
        var text = luminance > 0.55 ? Color.FromArgb(13, 17, 23) : Color.FromArgb(240, 246, 252);
        button.ForeColor = button.Enabled ? text : ThemeMutedText;
        button.FlatAppearance.BorderColor = ThemeBorder;
    }

    private static Color BlendTowardPanel(Color colour)
    {
        const double keep = 0.28;
        var panel = ThemeSectionBackground;
        return Color.FromArgb(
            (int)Math.Round((colour.R * keep) + (panel.R * (1 - keep))),
            (int)Math.Round((colour.G * keep) + (panel.G * (1 - keep))),
            (int)Math.Round((colour.B * keep) + (panel.B * (1 - keep))));
    }

    /// <summary>Repaint every swatch for the current enabled state.</summary>
    private void RefreshPartColourSwatchPaint()
    {
        foreach (var button in new[] { _partTintButton, _partRecolourButton, _partEmissiveButton })
        {
            if (button is not null)
            {
                SetPartColourSwatch(
                    button,
                    _partSwatchColours.TryGetValue(button, out var stored) ? stored : NeutralPartColour);
            }
        }
    }

    private void PickPartColour(Button? button, string title, Action<Color> onPicked)
    {
        if (button is null || !button.Enabled)
        {
            return;
        }
        // ColorDialog has no caption property, so the intent is carried by the
        // button the user pressed and by its accessible name.
        _ = title;
        using var dialog = new ColorDialog
        {
            Color = button.BackColor,
            FullOpen = true,
            AnyColor = true,
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        SetPartColourSwatch(button, dialog.Color);
        onPicked(dialog.Color);
    }
}
