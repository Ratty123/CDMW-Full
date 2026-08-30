namespace Cdmw.MeshEditorExperiment;

internal static partial class HeadlessGpuInteractionSoak
{
    private static Dictionary<string, object?> CaptureD3D11DebugLayerEvidence(
        MeshViewport viewport,
        ObjDocument document,
        NetMaterialSet materials,
        NetTextureSet textures)
    {
        var hardware = viewport.RendererDebugLayerEvidencePayload();
        var warp = D3D11DebugLayerEvidence.CaptureWarpRenderer(document, materials, textures);
        return new Dictionary<string, object?>
        {
            ["hardware"] = hardware,
            ["warp"] = warp,
            ["ok"] = EvidenceIsClean(hardware, "hardware")
                && EvidenceIsClean(warp, "warp"),
        };
    }

    private static void ApplyD3D11DebugLayerEvidence(
        Dictionary<string, object?> report,
        Dictionary<string, bool> gates,
        Dictionary<string, object?> evidence)
    {
        var hardware = EvidenceSection(evidence, "hardware");
        var warp = EvidenceSection(evidence, "warp");
        gates["hardware_d3d11_debug_layer_clean"] = EvidenceIsClean(hardware, "hardware");
        gates["warp_d3d11_debug_layer_clean"] = EvidenceIsClean(warp, "warp");
        gates["d3d11_adapter_provenance_recorded"] =
            AdapterRecorded(hardware) && AdapterRecorded(warp);
        report["d3d11_debug_layer"] = evidence;
    }

    private static IReadOnlyDictionary<string, object?> EvidenceSection(
        IReadOnlyDictionary<string, object?> evidence,
        string name) => evidence.GetValueOrDefault(name)
            as IReadOnlyDictionary<string, object?>
            ?? new Dictionary<string, object?>();

    private static bool EvidenceIsClean(
        IReadOnlyDictionary<string, object?> evidence,
        string expectedDriverType) =>
        evidence.GetValueOrDefault("ok") is true
        && string.Equals(
            Convert.ToString(evidence.GetValueOrDefault("driver_type")),
            expectedDriverType,
            StringComparison.Ordinal)
        && evidence.GetValueOrDefault("debug_layer_requested") is true
        && evidence.GetValueOrDefault("debug_layer_active") is true
        && evidence.GetValueOrDefault("capture_started") is true
        && Convert.ToInt64(evidence.GetValueOrDefault("stored_message_count") ?? -1) == 0
        && Convert.ToInt64(evidence.GetValueOrDefault("discarded_message_count") ?? -1) == 0;

    private static bool AdapterRecorded(IReadOnlyDictionary<string, object?> evidence) =>
        !string.IsNullOrWhiteSpace(Convert.ToString(evidence.GetValueOrDefault("adapter_description")))
        && !string.IsNullOrWhiteSpace(Convert.ToString(evidence.GetValueOrDefault("feature_level")));
}
