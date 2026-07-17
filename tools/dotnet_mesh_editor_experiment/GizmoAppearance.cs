using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

internal readonly record struct GizmoAppearance(
    Color XAxis,
    Color YAxis,
    Color ZAxis,
    Color Highlight,
    Color Label,
    float LineThicknessPixels,
    float SizeScale,
    float LabelSizePixels,
    float HandleSizePixels)
{
    internal const float MinimumLineThicknessPixels = 1.0f;
    internal const float MaximumLineThicknessPixels = 6.0f;
    internal const float MinimumSizeScale = 0.5f;
    internal const float MaximumSizeScale = 3.0f;
    internal const float MinimumLabelSizePixels = 8.0f;
    internal const float MaximumLabelSizePixels = 32.0f;
    internal const float MinimumHandleSizePixels = 4.0f;
    internal const float MaximumHandleSizePixels = 24.0f;

    public static GizmoAppearance Default { get; } = new(
        Color.FromArgb(235, 75, 75),
        Color.FromArgb(80, 220, 105),
        Color.FromArgb(75, 145, 255),
        Color.FromArgb(255, 225, 95),
        Color.FromArgb(245, 248, 252),
        1.0f,
        1.0f,
        12.0f,
        8.0f);

    public GizmoAppearance Normalized() => new(
        Opaque(XAxis),
        Opaque(YAxis),
        Opaque(ZAxis),
        Opaque(Highlight),
        Opaque(Label),
        Math.Clamp(LineThicknessPixels, MinimumLineThicknessPixels, MaximumLineThicknessPixels),
        Math.Clamp(SizeScale, MinimumSizeScale, MaximumSizeScale),
        Math.Clamp(LabelSizePixels, MinimumLabelSizePixels, MaximumLabelSizePixels),
        Math.Clamp(HandleSizePixels, MinimumHandleSizePixels, MaximumHandleSizePixels));

    public Color Axis(string handle) => handle switch
    {
        "x" => XAxis,
        "y" => YAxis,
        _ => ZAxis,
    };

    public float ScaleLength(float baseLength) => Math.Max(0.0001f, baseLength * SizeScale);

    public static string Hex(Color color) => $"#{color.R:X2}{color.G:X2}{color.B:X2}";

    public static Color ParseColor(string value, Color fallback)
    {
        var text = (value ?? string.Empty).Trim();
        return text.Length == 7
            && text[0] == '#'
            && int.TryParse(text.AsSpan(1, 2), System.Globalization.NumberStyles.HexNumber, null, out var red)
            && int.TryParse(text.AsSpan(3, 2), System.Globalization.NumberStyles.HexNumber, null, out var green)
            && int.TryParse(text.AsSpan(5, 2), System.Globalization.NumberStyles.HexNumber, null, out var blue)
                ? Color.FromArgb(red, green, blue)
                : fallback;
    }

    private static Color Opaque(Color color) => Color.FromArgb(color.R, color.G, color.B);
}
