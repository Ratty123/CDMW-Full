namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The weight the brush applies at a distance from its centre.
/// </summary>
/// <remarks>
/// A line-for-line port of <c>brush_falloff_weight</c> in
/// <c>native/cdmw_mesh_core/src/owners/geometry_uv_04.cpp</c>, which is the
/// authority: native mesh core is what actually weights a stroke. This copy
/// exists only so the falloff preview can draw the real profile instead of an
/// artist's impression of it, and a preview that disagreed with the brush would
/// be worse than no preview. Change the C++ first, then mirror it here.
/// </remarks>
internal static class BrushFalloffProfile
{
    public const string Smooth = "smooth";
    public const string Linear = "linear";
    public const string Sharp = "sharp";
    public const string Constant = "constant";

    public static double Weight(double distance, double radius, string falloff)
    {
        if (radius <= 1e-8)
        {
            return distance <= 1e-8 ? 1.0 : 0.0;
        }
        var normalized = Math.Max(0.0, Math.Min(1.0, distance / radius));
        if (normalized >= 1.0)
        {
            return 0.0;
        }
        if (falloff == Linear)
        {
            return 1.0 - normalized;
        }
        if (falloff == Sharp)
        {
            return (1.0 - normalized) * (1.0 - normalized);
        }
        if (falloff == Constant)
        {
            return 1.0;
        }
        var t = normalized;
        return 1.0 - (t * t * (3.0 - 2.0 * t));
    }
}
