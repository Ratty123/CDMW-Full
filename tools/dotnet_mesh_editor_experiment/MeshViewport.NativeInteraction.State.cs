using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private sealed class ResidentNativeGesture
    {
        internal required ulong GestureId { get; init; }
        internal required string OperatorGestureId { get; init; }
        internal required NativeMeshInteractionTool Tool { get; init; }
        internal required Point Start { get; init; }
        internal Point Previous { get; set; }
        internal NativeMeshSelectionTarget SelectionTarget { get; init; }
        internal NativeMeshSelectionShape SelectionShape { get; init; }
        internal NativeMeshSelectionOperation SelectionOperation { get; init; }
    }

    private readonly record struct ResidentNativeSnapshotStamp(
        ulong MeshRevision,
        ulong TopologyGeneration,
        ulong CameraRevision,
        ulong ViewportRevision,
        ulong VisiblePartsRevision,
        ulong ModelTransformRevision,
        bool XRay);

    private NativeMeshInteractionAbi? _residentNativeAbi;
    private NativeMeshInteractionSession? _residentNativeSession;
    private ResidentNativeGesture? _residentNativeGesture;
    private readonly Dictionary<int, List<Vec3>> _residentNativePreviewPositions = new();
    private readonly Dictionary<ulong, ResidentInteractionTransactionLease> _residentNativeTransactions = new();
    private readonly Dictionary<long, ResidentInteractionTransactionLease> _residentNativeTransactionsByRequest = new();
    private string _residentNativeSessionId = string.Empty;
    private string _residentNativeFailure = string.Empty;
    private string _residentNativeLastGestureFailure = string.Empty;
    private ObjDocument? _residentNativeDocument;
    private ulong _residentNativeMeshRevision;
    private ulong _residentNativeSelectionRevision;
    private ulong _residentNativeTopologyGeneration;
    private ulong _residentNativeCameraRevision;
    private ulong _residentNativeViewportRevision;
    private ulong _residentNativeVisiblePartsRevision;
    private ulong _residentNativeModelTransformRevision;
    private ulong _residentNativeGestureSequence;
    private ulong _residentNativeTransactionSequence;
    private long _residentNativePendingTransactionBytes;
    private ulong _residentNativeDurableRevision;
    private ulong _residentNativeDurableSelectionRevision;
    private ulong _residentNativeDurableTopologyGeneration;
    private Matrix4x4 _residentNativeCameraMatrix;
    private NativeMeshProjectionData[] _residentNativeProjections = [];
    private int[] _residentNativeVisibleParts = [];
    private NativeMeshProjectionData[] _residentNativeModelTransforms = [];
    private Size _residentNativeViewportSize;
    private bool _residentNativeCameraValid;
    private bool _residentNativeRequired;
    private bool _residentNativeAwaitingAuthority;
    private bool _residentNativeReplicationRejected;
    private System.Windows.Forms.Timer? _residentNativeReplicationTimer;
    private CancellationTokenSource? _residentNativeSnapshotCancellation;
    private Task? _residentNativeSnapshotTask;
    private long _residentNativeSnapshotGeneration;
    private ResidentNativeSnapshotStamp? _residentNativeSnapshotRequested;
    private ResidentNativeSnapshotStamp? _residentNativeSnapshotReady;
    private System.Windows.Forms.Timer? _residentNativeSnapshotSyncTimer;

    private const int ResidentNativeMaximumPendingTransactions = 16;
    private const long ResidentNativeMaximumPendingBytes = 64L * 1024L * 1024L;

    internal bool ResidentNativeInteractionRequired => _residentNativeRequired;
    internal bool ResidentNativeInteractionReady =>
        _residentNativeRequired && _residentNativeSession is not null && _residentNativeFailure.Length == 0;
    internal bool ResidentNativeReplicationPending => _residentNativeTransactions.Count > 0;
    internal bool ResidentNativeReplicationBlocked => _residentNativeReplicationRejected
        || _residentNativeTransactions.Count >= ResidentNativeMaximumPendingTransactions
        || _residentNativePendingTransactionBytes >= ResidentNativeMaximumPendingBytes;

    internal Dictionary<string, object?> ResidentNativeInteractionDiagnostics() => new()
    {
        ["required"] = _residentNativeRequired,
        ["ready"] = ResidentNativeInteractionReady,
        ["failure"] = _residentNativeFailure,
        ["last_gesture_failure"] = _residentNativeLastGestureFailure,
        ["session_id"] = _residentNativeSessionId,
        ["mesh_revision"] = _residentNativeMeshRevision,
        ["selection_revision"] = _residentNativeSelectionRevision,
        ["topology_generation"] = _residentNativeTopologyGeneration,
        ["camera_revision"] = _residentNativeCameraRevision,
        ["visible_parts_revision"] = _residentNativeVisiblePartsRevision,
        ["model_transform_revision"] = _residentNativeModelTransformRevision,
        ["projection_count"] = _residentNativeProjections.Length,
        ["selection_projection"] = ResidentNativeSelectionProjectionDiagnostics(),
        ["viewport_revision"] = _residentNativeViewportRevision,
        ["awaiting_authority"] = _residentNativeAwaitingAuthority,
        ["pending_transactions"] = _residentNativeTransactions.Count,
        ["pending_transaction_bytes"] = _residentNativePendingTransactionBytes,
        ["durable_revision"] = _residentNativeDurableRevision,
        ["durable_selection_revision"] = _residentNativeDurableSelectionRevision,
        ["durable_topology_generation"] = _residentNativeDurableTopologyGeneration,
        ["replication_blocked"] = ResidentNativeReplicationBlocked,
        ["replication_rejected"] = _residentNativeReplicationRejected,
        ["indexed_snapshot_ready"] = _residentNativeSnapshotReady.HasValue,
        ["indexed_snapshot_generation"] = _residentNativeSnapshotGeneration,
        ["input_handler_timing"] = ResidentNativeInputHandlerTimingDiagnostics(),
        ["provisional_feedback_timing"] = ResidentNativeProvisionalFeedbackTimingDiagnostics(),
        ["library_path"] = _residentNativeAbi?.Diagnostics.LibraryPath ?? string.Empty,
        ["library_sha256"] = _residentNativeAbi?.Diagnostics.LibrarySha256 ?? string.Empty,
        ["abi_version"] = _residentNativeAbi?.Diagnostics.AbiVersion ?? 0,
        ["contract"] = _residentNativeAbi?.Diagnostics.Contract ?? string.Empty,
        ["backend"] = _residentNativeAbi?.Diagnostics.Backend ?? string.Empty,
        ["header_sha256"] = _residentNativeAbi?.Diagnostics.HeaderSha256 ?? string.Empty,
    };

    private Dictionary<string, object?> ResidentNativeSelectionProjectionDiagnostics()
    {
        var viewport = ActivePaneBounds();
        var camera = CurrentCamera();
        var projections = ResidentNativeProjections(camera);
        return new Dictionary<string, object?>
        {
            ["viewport_width"] = Math.Max(1, viewport.Width),
            ["viewport_height"] = Math.Max(1, viewport.Height),
            ["world_view_projection"] = MatrixRowMajorArray(camera.WorldViewProjection),
            ["source_submesh_indices"] = projections
                .Select(projection => projection.SubmeshIndex)
                .ToArray(),
            ["source_submesh_world_view_projections"] = projections
                .Select(projection => new Dictionary<string, object?>
                {
                    ["source_submesh_index"] = projection.SubmeshIndex,
                    ["world_view_projection"] = projection.WorldViewProjection,
                })
                .ToArray(),
            ["pane_bounds_diagnostics"] = PaneBoundsDiagnostics(),
        };
    }
}
