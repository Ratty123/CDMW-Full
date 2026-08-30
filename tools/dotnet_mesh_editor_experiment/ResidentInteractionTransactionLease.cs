using System.IO.MemoryMappedFiles;
using System.Security.Cryptography;

namespace Cdmw.MeshEditorExperiment;

internal sealed class ResidentInteractionTransactionLease : IDisposable
{
    private MemoryMappedFile? _mapping;

    private ResidentInteractionTransactionLease(
        MemoryMappedFile mapping,
        string mappingName,
        byte[] payload,
        ulong gestureId,
        string operatorGestureId,
        NativeMeshInteractionTool tool,
        ulong baseMeshRevision,
        ulong targetMeshRevision,
        ulong baseSelectionRevision,
        ulong targetSelectionRevision,
        ulong topologyGeneration)
    {
        _mapping = mapping;
        MappingName = mappingName;
        Length = payload.Length;
        Sha256 = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
        GestureId = gestureId;
        OperatorGestureId = operatorGestureId;
        Tool = tool;
        BaseMeshRevision = baseMeshRevision;
        TargetMeshRevision = targetMeshRevision;
        BaseSelectionRevision = baseSelectionRevision;
        TargetSelectionRevision = targetSelectionRevision;
        TopologyGeneration = topologyGeneration;
    }

    internal string MappingName { get; }
    internal int Length { get; }
    internal string Sha256 { get; }
    internal ulong GestureId { get; }
    internal string OperatorGestureId { get; }
    internal NativeMeshInteractionTool Tool { get; }
    internal ulong BaseMeshRevision { get; }
    internal ulong TargetMeshRevision { get; }
    internal ulong BaseSelectionRevision { get; }
    internal ulong TargetSelectionRevision { get; }
    internal ulong TopologyGeneration { get; }
    internal long RequestId { get; set; }

    internal static ResidentInteractionTransactionLease Create(
        byte[] payload,
        ulong gestureId,
        string operatorGestureId,
        NativeMeshInteractionTool tool,
        ulong baseMeshRevision,
        ulong targetMeshRevision,
        ulong baseSelectionRevision,
        ulong targetSelectionRevision,
        ulong topologyGeneration)
    {
        ArgumentNullException.ThrowIfNull(payload);
        var name = $"Local\\CDMW.MeshInteraction.{Guid.NewGuid():N}";
        var mapping = MemoryMappedFile.CreateNew(
            name,
            payload.Length,
            MemoryMappedFileAccess.ReadWrite);
        using (var view = mapping.CreateViewStream(0, payload.Length, MemoryMappedFileAccess.Write))
        {
            view.Write(payload, 0, payload.Length);
            view.Flush();
        }
        return new ResidentInteractionTransactionLease(
            mapping,
            name,
            payload,
            gestureId,
            operatorGestureId,
            tool,
            baseMeshRevision,
            targetMeshRevision,
            baseSelectionRevision,
            targetSelectionRevision,
            topologyGeneration);
    }

    internal Dictionary<string, object?> Descriptor(string sessionId) => new()
    {
        ["mapping_name"] = MappingName,
        ["length"] = Length,
        ["sha256"] = Sha256,
        ["session_id"] = sessionId,
        ["gesture_id"] = GestureId,
        ["base_revision"] = BaseMeshRevision,
        ["base_selection_revision"] = BaseSelectionRevision,
        ["topology_generation"] = TopologyGeneration,
        ["format_version"] = 1,
    };

    public void Dispose()
    {
        Interlocked.Exchange(ref _mapping, null)?.Dispose();
    }
}
