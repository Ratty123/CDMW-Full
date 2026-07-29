using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The held modifiers that hand the left mouse button to the camera while an
/// edit tool owns it, and the labels that name them on the navigation strip.
/// </summary>
/// <remarks>
/// Pan is tested before orbit, so a modifier bound to both pans. The host is
/// expected to send a non-overlapping pair — <c>cdmw.domain.camera_bindings</c>
/// resolves that before it reaches the wire — but the viewport must stay
/// predictable if it ever receives one anyway, rather than depending on which
/// gesture happened to be checked first.
/// </remarks>
internal static class CameraModifierBindings
{
    public const string Alt = "alt";
    public const string Ctrl = "ctrl";
    public const string Shift = "shift";
    public const string AltOrCtrl = "alt_or_ctrl";

    /// <summary>
    /// Ctrl was the binding this editor shipped with and Alt is the one every
    /// other mesh application uses, so the default honours both.
    /// </summary>
    public const string DefaultOrbit = AltOrCtrl;
    public const string DefaultPan = Shift;

    public static string Normalize(string? value, string fallback)
    {
        return (value ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            Alt => Alt,
            Ctrl => Ctrl,
            Shift => Shift,
            AltOrCtrl => AltOrCtrl,
            _ => fallback,
        };
    }

    public static bool IsHeld(string binding, Keys modifiers)
    {
        return binding switch
        {
            Alt => (modifiers & Keys.Alt) == Keys.Alt,
            Ctrl => (modifiers & Keys.Control) == Keys.Control,
            Shift => (modifiers & Keys.Shift) == Keys.Shift,
            AltOrCtrl => (modifiers & Keys.Alt) == Keys.Alt
                || (modifiers & Keys.Control) == Keys.Control,
            _ => false,
        };
    }
}
