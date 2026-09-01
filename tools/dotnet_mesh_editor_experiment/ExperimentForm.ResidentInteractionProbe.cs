using System.Drawing;
using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    /// <summary>
    /// Handles the additive visible-harness probe on the normal parsed-message
    /// drain. The viewport owns the gesture and emits any terminal transaction;
    /// this handler only correlates the diagnostic result.
    /// </summary>
    private void HandleResidentInteractionProbe(JsonElement root)
    {
        var requestId = JsonLongValue(root, "request_id");
        var mode = JsonString(root, "mode").Trim().ToLowerInvariant();
        var response = new Dictionary<string, object?>
        {
            ["ok"] = false,
            ["status"] = "rejected",
            ["request_id"] = requestId,
            ["session_id"] = _residentMaterialSessionId,
            ["process_generation"] = _residentProcessGeneration,
            ["protocol_version"] = 3,
            ["mode"] = mode,
            ["point_count"] = 0,
            ["sample_count"] = 0,
            ["mouse_down_route"] = "resident_probe_direct",
            ["core_route"] = "resident_native_interaction",
            ["begin_ms"] = 0.0,
            ["input_sample_p95_ms"] = 0.0,
            ["input_sample_max_ms"] = 0.0,
            ["finish_ms"] = 0.0,
            ["total_ms"] = 0.0,
        };

        try
        {
            if (requestId <= 0)
            {
                throw new InvalidOperationException("resident_interaction_probe requires request_id.");
            }
            if (!TryReadResidentInteractionProbePoint(
                    root,
                    "start",
                    "start_x",
                    "start_y",
                    out var start)
                || !TryReadResidentInteractionProbePoint(
                    root,
                    "end",
                    "end_x",
                    "end_y",
                    out var end))
            {
                throw new InvalidOperationException(
                    "resident_interaction_probe requires finite start and end points.");
            }

            var rawSampleCount = JsonLongValue(root, "sample_count");
            var requestedSampleCount = rawSampleCount > int.MaxValue
                ? int.MaxValue
                : (int)rawSampleCount;
            var result = _viewport.RunResidentInteractionProbe(
                mode,
                start,
                end,
                requestedSampleCount);
            foreach (var entry in result)
            {
                response[entry.Key] = entry.Value;
            }
        }
        catch (Exception exception)
        {
            response["error"] = $"{exception.GetType().Name}: {exception.Message}";
        }

        // Probe requests are diagnostic, not mutating host requests, so the
        // normal output writer will not manufacture a new correlation envelope.
        // Carry the current identity and the caller's request id explicitly.
        response["session_id"] = _residentMaterialSessionId;
        response["process_generation"] = _residentProcessGeneration;
        response["request_id"] = requestId;
        WriteProtocolEvent("resident_interaction_probe_applied", response);
    }

    private static bool TryReadResidentInteractionProbePoint(
        JsonElement root,
        string pointName,
        string xName,
        string yName,
        out Point point)
    {
        point = Point.Empty;
        if (root.TryGetProperty(pointName, out var pointValue))
        {
            if (pointValue.ValueKind == JsonValueKind.Object)
            {
                if (pointValue.TryGetProperty("x", out var objectXValue)
                    && pointValue.TryGetProperty("y", out var objectYValue)
                    && TryResidentInteractionProbeCoordinate(objectXValue, out var objectX)
                    && TryResidentInteractionProbeCoordinate(objectYValue, out var objectY))
                {
                    point = ResidentInteractionProbePoint(objectX, objectY);
                    return true;
                }
            }
            else if (pointValue.ValueKind == JsonValueKind.Array)
            {
                var coordinates = pointValue.EnumerateArray().Take(2).ToArray();
                if (coordinates.Length == 2
                    && TryResidentInteractionProbeCoordinate(coordinates[0], out var arrayX)
                    && TryResidentInteractionProbeCoordinate(coordinates[1], out var arrayY))
                {
                    point = ResidentInteractionProbePoint(arrayX, arrayY);
                    return true;
                }
            }
        }

        var x = JsonDoubleValue(root, xName, double.NaN);
        var y = JsonDoubleValue(root, yName, double.NaN);
        if (!double.IsFinite(x) || !double.IsFinite(y))
        {
            return false;
        }
        point = ResidentInteractionProbePoint(x, y);
        return true;
    }

    private static bool TryResidentInteractionProbeCoordinate(
        JsonElement value,
        out double coordinate)
    {
        if (value.ValueKind == JsonValueKind.Number
            && value.TryGetDouble(out var numeric)
            && double.IsFinite(numeric))
        {
            coordinate = numeric;
            return true;
        }
        if (value.ValueKind == JsonValueKind.String
            && double.TryParse(
                value.GetString(),
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out var parsed)
            && double.IsFinite(parsed))
        {
            coordinate = parsed;
            return true;
        }
        coordinate = 0.0;
        return false;
    }

    private static Point ResidentInteractionProbePoint(double x, double y) =>
        new(
            (int)Math.Clamp(
                Math.Round(x, MidpointRounding.AwayFromZero),
                -1_000_000d,
                1_000_000d),
            (int)Math.Clamp(
                Math.Round(y, MidpointRounding.AwayFromZero),
                -1_000_000d,
                1_000_000d));
}
