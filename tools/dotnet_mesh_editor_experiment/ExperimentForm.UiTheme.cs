using System.Globalization;
using System.Drawing;
using System.Diagnostics;
using System.Text.Json;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private readonly record struct UiThemePalette(
        Color Window,
        Color Surface,
        Color SurfaceAlt,
        Color Field,
        Color Border,
        Color BorderStrong,
        Color Text,
        Color TextMuted,
        Color TextStrong,
        Color Button,
        Color ButtonHover,
        Color ButtonPressed,
        Color ButtonBorder,
        Color Accent,
        Color AccentHover,
        Color AccentPressed);

    private void HandleUiThemeState(JsonElement root)
    {
        var themeKey = JsonString(root, "theme_key");
        var applied = TryApplyUiThemeState(root, out var reason);
        WriteProtocolEvent("ui_theme_state_ack", new Dictionary<string, object?>
        {
            ["status"] = applied ? "applied" : "rejected",
            ["reason"] = reason,
            ["theme_key"] = themeKey,
            ["window"] = ThemeHex(ThemeWindowBackground),
            ["surface"] = ThemeHex(ThemePanelBackground),
            ["accent"] = ThemeHex(ThemeAccent),
        });
    }

    private bool TryApplyUiThemeState(JsonElement root, out string reason)
    {
        reason = string.Empty;
        if (!root.TryGetProperty("palette", out var colors)
            || colors.ValueKind != JsonValueKind.Object
            || !TryReadUiThemePalette(colors, out var palette))
        {
            reason = "invalid_palette";
            return false;
        }
        ApplyUiThemePalette(palette);
        StartupTiming.Mark("ui_theme_state_applied");
        return true;
    }

    private static bool TryReadUiThemePalette(JsonElement colors, out UiThemePalette palette)
    {
        palette = default;
        if (!TryThemeColor(colors, "window", out var window)
            || !TryThemeColor(colors, "surface", out var surface)
            || !TryThemeColor(colors, "surface_alt", out var surfaceAlt)
            || !TryThemeColor(colors, "field", out var field)
            || !TryThemeColor(colors, "border", out var border)
            || !TryThemeColor(colors, "border_strong", out var borderStrong)
            || !TryThemeColor(colors, "text", out var text)
            || !TryThemeColor(colors, "text_muted", out var textMuted)
            || !TryThemeColor(colors, "text_strong", out var textStrong)
            || !TryThemeColor(colors, "button", out var button)
            || !TryThemeColor(colors, "button_hover", out var buttonHover)
            || !TryThemeColor(colors, "button_pressed", out var buttonPressed)
            || !TryThemeColor(colors, "button_border", out var buttonBorder)
            || !TryThemeColor(colors, "accent", out var accent))
        {
            return false;
        }
        palette = new UiThemePalette(
            window,
            surface,
            surfaceAlt,
            field,
            border,
            borderStrong,
            text,
            textMuted,
            textStrong,
            button,
            buttonHover,
            buttonPressed,
            buttonBorder,
            accent,
            BlendColor(accent, Color.White, 0.16f),
            BlendColor(accent, Color.Black, 0.24f));
        return true;
    }

    private static bool TryThemeColor(JsonElement colors, string key, out Color color)
    {
        color = default;
        if (!colors.TryGetProperty(key, out var value)
            || value.ValueKind != JsonValueKind.String)
        {
            return false;
        }
        var text = value.GetString() ?? string.Empty;
        if (text.Length != 7
            || text[0] != '#'
            || !int.TryParse(
                text.AsSpan(1),
                NumberStyles.AllowHexSpecifier,
                CultureInfo.InvariantCulture,
                out var rgb))
        {
            return false;
        }
        color = Color.FromArgb((rgb >> 16) & 0xff, (rgb >> 8) & 0xff, rgb & 0xff);
        return true;
    }

    private void ApplyUiThemePalette(UiThemePalette palette)
    {
        var previous = CurrentUiThemePalette();
        SetCurrentUiThemePalette(palette);
        SuspendLayout();
        try
        {
            ApplyThemeToControlTree(this, previous, palette);
            _helpToolTip.BackColor = palette.SurfaceAlt;
            _helpToolTip.ForeColor = palette.TextStrong;
        }
        finally
        {
            ResumeLayout(performLayout: true);
        }
        Invalidate(invalidateChildren: true);
    }

    private static UiThemePalette CurrentUiThemePalette() => new(
        ThemeWindowBackground,
        ThemePanelBackground,
        ThemeRailBackground,
        ThemeInputBackground,
        Color.FromArgb(42, 45, 46),
        ThemeBorder,
        ThemeText,
        ThemeMutedText,
        ThemeStrongText,
        ThemeButtonBackground,
        ThemeButtonHover,
        ThemeButtonPressed,
        ThemeButtonBorder,
        ThemeAccent,
        ThemeAccentHover,
        ThemeAccentPressed);

    private static void SetCurrentUiThemePalette(UiThemePalette palette)
    {
        ThemeWindowBackground = palette.Window;
        ThemePanelBackground = palette.Surface;
        ThemeSectionBackground = palette.Surface;
        ThemeRailBackground = palette.SurfaceAlt;
        ThemeInputBackground = palette.Field;
        ThemeButtonBackground = palette.Button;
        ThemeButtonHover = palette.ButtonHover;
        ThemeButtonPressed = palette.ButtonPressed;
        ThemeButtonBorder = palette.ButtonBorder;
        ThemeBorder = palette.BorderStrong;
        ThemeAccent = palette.Accent;
        ThemeAccentHover = palette.AccentHover;
        ThemeAccentPressed = palette.AccentPressed;
        ThemeText = palette.Text;
        ThemeStrongText = palette.TextStrong;
        ThemeMutedText = palette.TextMuted;
        ThemeStatusBackground = palette.Window;
    }

    private static void ApplyThemeToControlTree(
        Control control,
        UiThemePalette previous,
        UiThemePalette current)
    {
        control.BackColor = RemapThemeBackground(control, control.BackColor, previous, current);
        control.ForeColor = RemapThemeForeground(control.ForeColor, previous, current);
        if (control is ButtonBase button)
        {
            button.FlatAppearance.MouseOverBackColor = RemapThemeHover(
                button.FlatAppearance.MouseOverBackColor,
                previous,
                current);
            button.FlatAppearance.MouseDownBackColor = RemapThemePressed(
                button.FlatAppearance.MouseDownBackColor,
                previous,
                current);
            button.FlatAppearance.BorderColor = RemapThemeBorder(
                button.FlatAppearance.BorderColor,
                previous,
                current);
        }
        if (control.IsHandleCreated)
        {
            ApplyNativeControlTheme(control);
        }
        foreach (Control child in control.Controls)
        {
            ApplyThemeToControlTree(child, previous, current);
        }
        control.Invalidate();
    }

    private static Color RemapThemeBackground(
        Control control,
        Color color,
        UiThemePalette previous,
        UiThemePalette current)
    {
        if (control is ButtonBase)
        {
            if (SameThemeColor(color, previous.Accent)) return current.Accent;
            if (SameThemeColor(color, previous.Button)) return current.Button;
        }
        if (control is TextBoxBase or ListBox or ListView or ComboBox or NumericUpDown)
        {
            if (SameThemeColor(color, previous.Field)) return current.Field;
        }
        if (SameThemeColor(color, previous.Window)) return current.Window;
        if (SameThemeColor(color, previous.Surface)) return current.Surface;
        if (SameThemeColor(color, previous.SurfaceAlt)) return current.SurfaceAlt;
        if (SameThemeColor(color, previous.Field)) return current.Field;
        if (SameThemeColor(color, previous.Accent)) return current.Accent;
        return color;
    }

    private static Color RemapThemeForeground(
        Color color,
        UiThemePalette previous,
        UiThemePalette current)
    {
        if (SameThemeColor(color, previous.Text)) return current.Text;
        if (SameThemeColor(color, previous.TextMuted)) return current.TextMuted;
        if (SameThemeColor(color, previous.TextStrong)) return current.TextStrong;
        return color;
    }

    private static Color RemapThemeHover(Color color, UiThemePalette previous, UiThemePalette current)
    {
        if (SameThemeColor(color, previous.AccentHover)) return current.AccentHover;
        if (SameThemeColor(color, previous.ButtonHover)) return current.ButtonHover;
        return color;
    }

    private static Color RemapThemePressed(Color color, UiThemePalette previous, UiThemePalette current)
    {
        if (SameThemeColor(color, previous.AccentPressed)) return current.AccentPressed;
        if (SameThemeColor(color, previous.ButtonPressed)) return current.ButtonPressed;
        return color;
    }

    private static Color RemapThemeBorder(Color color, UiThemePalette previous, UiThemePalette current)
    {
        if (SameThemeColor(color, previous.ButtonBorder)) return current.ButtonBorder;
        if (SameThemeColor(color, previous.BorderStrong)) return current.BorderStrong;
        return color;
    }

    private static bool SameThemeColor(Color left, Color right) => left.ToArgb() == right.ToArgb();

    private static bool ThemeUsesDarkControls() =>
        (ThemeWindowBackground.R * 299
            + ThemeWindowBackground.G * 587
            + ThemeWindowBackground.B * 114) < 128_000;

    private static void ApplyNativeControlTheme(Control control)
    {
        if (!control.IsHandleCreated) return;
        _ = SetWindowTheme(
            control.Handle,
            ThemeUsesDarkControls() ? "DarkMode_Explorer" : "Explorer",
            null);
    }

    private static string ThemeHex(Color color) =>
        $"#{color.R:x2}{color.G:x2}{color.B:x2}";

    internal Dictionary<string, object?> UiThemeStateProof()
    {
        using var light = JsonDocument.Parse(
            """{"theme_key":"light","palette":{"window":"#f4f6f8","surface":"#ffffff","surface_alt":"#eef2f6","field":"#ffffff","border":"#d5dde6","border_strong":"#c6d0dc","text":"#1f2933","text_muted":"#5f6c7b","text_strong":"#111827","button":"#e7edf4","button_hover":"#dbe4ee","button_pressed":"#cfd9e4","button_border":"#b8c5d3","accent":"#2563eb"}}""");
        var lightStarted = Stopwatch.GetTimestamp();
        var lightApplied = TryApplyUiThemeState(light.RootElement, out var lightReason);
        var lightMilliseconds = Stopwatch.GetElapsedTime(lightStarted).TotalMilliseconds;
        var lightMatches = lightApplied
            && ThemeHex(BackColor) == "#f4f6f8"
            && ThemeHex(_submeshList.BackColor) == "#ffffff"
            && ThemeHex(_geometryLayerList.BackColor) == "#ffffff"
            && ThemeHex(_statusLabel.ForeColor) == "#1f2933"
            && ThemeHex(_statusLabel.BackColor) == "#f4f6f8"
            && _undoButton is not null
            && ThemeHex(_undoButton.BackColor) == "#e7edf4"
            && !ThemeUsesDarkControls();

        using var crimson = JsonDocument.Parse(
            """{"theme_key":"crimson_desert","palette":{"window":"#211814","surface":"#2a1d18","surface_alt":"#35241c","field":"#1b130f","border":"#513929","border_strong":"#6b4932","text":"#d9c0aa","text_muted":"#a98c77","text_strong":"#f4ddc4","button":"#35241c","button_hover":"#443025","button_pressed":"#2b1d17","button_border":"#6b4932","accent":"#c56d43"}}""");
        var crimsonStarted = Stopwatch.GetTimestamp();
        var crimsonApplied = TryApplyUiThemeState(crimson.RootElement, out var crimsonReason);
        var crimsonMilliseconds = Stopwatch.GetElapsedTime(crimsonStarted).TotalMilliseconds;
        var crimsonMatches = crimsonApplied
            && ThemeHex(BackColor) == "#211814"
            && ThemeHex(_submeshList.BackColor) == "#1b130f"
            && ThemeHex(_geometryLayerList.BackColor) == "#1b130f"
            && ThemeHex(_statusLabel.ForeColor) == "#d9c0aa"
            && ThemeHex(_statusLabel.BackColor) == "#211814"
            && _undoButton is not null
            && ThemeHex(_undoButton.BackColor) == "#35241c"
            && ThemeUsesDarkControls();
        return new Dictionary<string, object?>
        {
            ["ok"] = lightMatches
                && crimsonMatches
                && lightMilliseconds <= 250.0
                && crimsonMilliseconds <= 250.0,
            ["light_applied"] = lightApplied,
            ["light_reason"] = lightReason,
            ["light_controls_match"] = lightMatches,
            ["light_ms"] = lightMilliseconds,
            ["crimson_applied"] = crimsonApplied,
            ["crimson_reason"] = crimsonReason,
            ["crimson_controls_match"] = crimsonMatches,
            ["crimson_ms"] = crimsonMilliseconds,
            ["final_window"] = ThemeHex(BackColor),
            ["final_input"] = ThemeHex(_submeshList.BackColor),
            ["final_text"] = ThemeHex(_statusLabel.ForeColor),
        };
    }
}
