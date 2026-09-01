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
        ulong transactionSequence,
        string operatorGestureId,
        NativeMeshInteractionTool tool,
        ulong baseMeshRevision,
        ulong targetMeshRevision,
        ulong baseSelectionRevision,
        ulong targetSelectionRevision,
        ulong topologyGeneration,
        IReadOnlyDictionary<int, SortedDictionary<uint, (double X, double Y, double Z)>> geometry,
        Dictionary<int, Dictionary<uint, Vec3>> baselineGeometry,
        MeshViewport.ResidentMutationSelectionSnapshot baselineSelection)
    {
        _mapping = mapping;
        MappingName = mappingName;
        Length = payload.Length;
        Sha256 = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
        GestureId = gestureId;
        TransactionSequence = transactionSequence;
        OperatorGestureId = operatorGestureId;
        Tool = tool;
        BaseMeshRevision = baseMeshRevision;
        TargetMeshRevision = targetMeshRevision;
        BaseSelectionRevision = baseSelectionRevision;
        TargetSelectionRevision = targetSelectionRevision;
        TopologyGeneration = topologyGeneration;
        Geometry = geometry;
        BaselineGeometry = baselineGeometry;
        BaselineSelection = baselineSelection;
    }

    internal string MappingName { get; }
    internal int Length { get; }
    internal string Sha256 { get; }
    internal ulong GestureId { get; }
    internal ulong TransactionSequence { get; }
    internal string OperatorGestureId { get; }
    internal NativeMeshInteractionTool Tool { get; }
    internal ulong BaseMeshRevision { get; }
    internal ulong TargetMeshRevision { get; }
    internal ulong BaseSelectionRevision { get; }
    internal ulong TargetSelectionRevision { get; }
    internal ulong TopologyGeneration { get; }
    internal IReadOnlyDictionary<int, SortedDictionary<uint, (double X, double Y, double Z)>> Geometry { get; }
    internal Dictionary<int, Dictionary<uint, Vec3>> BaselineGeometry { get; }
    internal MeshViewport.ResidentMutationSelectionSnapshot BaselineSelection { get; }
    internal long RequestId { get; set; }
    internal DateTime PublishedUtc { get; set; }
    internal int RetryCount { get; set; }

    internal static ResidentInteractionTransactionLease Create(
        byte[] payload,
        ulong gestureId,
        ulong transactionSequence,
        string operatorGestureId,
        NativeMeshInteractionTool tool,
        ulong baseMeshRevision,
        ulong targetMeshRevision,
        ulong baseSelectionRevision,
        ulong targetSelectionRevision,
        ulong topologyGeneration,
        IReadOnlyDictionary<int, SortedDictionary<uint, (double X, double Y, double Z)>> geometry,
        Dictionary<int, Dictionary<uint, Vec3>> baselineGeometry,
        MeshViewport.ResidentMutationSelectionSnapshot baselineSelection)
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
            transactionSequence,
            operatorGestureId,
            tool,
            baseMeshRevision,
            targetMeshRevision,
            baseSelectionRevision,
            targetSelectionRevision,
            topologyGeneration,
            geometry,
            baselineGeometry,
            baselineSelection);
    }

    internal Dictionary<string, object?> Descriptor(string sessionId) => new()
    {
        ["mapping_name"] = MappingName,
        ["length"] = Length,
        ["sha256"] = Sha256,
        ["session_id"] = sessionId,
        ["gesture_id"] = GestureId,
        ["transaction_sequence"] = TransactionSequence,
        ["tool"] = (uint)Tool,
        ["base_revision"] = BaseMeshRevision,
        ["target_revision"] = TargetMeshRevision,
        ["base_selection_revision"] = BaseSelectionRevision,
        ["target_selection_revision"] = TargetSelectionRevision,
        ["topology_generation"] = TopologyGeneration,
        ["helper_process_id"] = Environment.ProcessId,
        ["format_version"] = 2,
    };

    public void Dispose()
    {
        Interlocked.Exchange(ref _mapping, null)?.Dispose();
    }
}
