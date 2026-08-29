using System.Globalization;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private static double NumberOption(Dictionary<string, object?> options, string key, double fallback)
    {
        return options.TryGetValue(key, out var value) && value is IConvertible
            ? Convert.ToDouble(value, CultureInfo.InvariantCulture)
            : fallback;
    }
}
