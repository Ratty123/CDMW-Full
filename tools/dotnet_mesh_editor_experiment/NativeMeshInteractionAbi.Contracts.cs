using System.Collections.ObjectModel;

namespace Cdmw.MeshEditorExperiment;

internal enum NativeMeshInteractionStatus : uint
{
    Ok = 0,
    InvalidArgument = 1,
    InvalidSize = 2,
    UnsupportedVersion = 3,
    SessionNotFound = 4,
    SessionExists = 5,
    RevisionMismatch = 6,
    Busy = 7,
    InvalidState = 8,
    BufferTooSmall = 9,
    Rejected = 10,
    InternalError = 11,
}

[Flags]
internal enum NativeMeshInteractionSyncFlags : uint
{
    Mesh = 1u << 0,
    Selection = 1u << 1,
    Topology = 1u << 2,
    Camera = 1u << 3,
    Viewport = 1u << 4,
}

internal enum NativeMeshInteractionTool : uint
{
    Select = 1,
    Move = 2,
    Grab = 3,
    Smooth = 4,
    Inflate = 5,
    Pinch = 6,
}

internal enum NativeMeshSelectionTarget : uint
{
    Vertex = 1,
    Edge = 2,
    Face = 3,
}

internal enum NativeMeshSelectionShape : uint
{
    Brush = 1,
    Rectangle = 2,
    Lasso = 3,
}

internal enum NativeMeshSelectionOperation : uint
{
    Replace = 1,
    Add = 2,
    Subtract = 3,
    Toggle = 4,
}

internal enum NativeMeshInteractionAuthorityAction : uint
{
    Accepted = 1,
    Rejected = 2,
    Undo = 3,
    Redo = 4,
}

internal enum NativeMeshInteractionOperatorState : uint
{
    Idle = 0,
    Active = 1,
    AwaitingAuthority = 2,
}

internal enum NativeMeshInteractionStructId : uint
{
    SubmeshV1 = 1,
    SelectionV1 = 2,
    OpenV1 = 3,
    SessionV1 = 4,
    SyncV1 = 5,
    GestureV1 = 6,
    AuthorityV1 = 7,
    VertexReadV1 = 8,
    DirtyRangeV1 = 9,
    SelectionChangeV1 = 10,
    ResultV1 = 11,
    ProjectionV1 = 12,
    PrepareSnapshotV1 = 13,
}

internal sealed record NativeMeshSubmeshData(
    int SubmeshIndex,
    double[] PositionsXyz,
    double[]? NormalsXyz,
    uint[] TriangleIndices
);

internal sealed record NativeMeshSelectionData(
    int SubmeshIndex,
    uint[] VertexIndices,
    uint[] FaceIndices,
    uint[] EdgeVertexPairs
);

internal sealed record NativeMeshProjectionData(
    int SubmeshIndex,
    double[] WorldViewProjection
);

internal sealed record NativeMeshInteractionOpenRequest(
    ulong SessionKey,
    ulong MeshRevision,
    ulong SelectionRevision,
    ulong TopologyGeneration,
    ulong CameraRevision,
    ulong ViewportRevision,
    IReadOnlyList<NativeMeshSubmeshData> Submeshes
);

internal sealed class NativeMeshInteractionSyncRequest
{
    public NativeMeshInteractionSyncFlags Flags { get; init; }
    public ulong BaseMeshRevision { get; init; }
    public ulong MeshRevision { get; init; }
    public ulong BaseSelectionRevision { get; init; }
    public ulong SelectionRevision { get; init; }
    public ulong BaseTopologyGeneration { get; init; }
    public ulong TopologyGeneration { get; init; }
    public ulong BaseCameraRevision { get; init; }
    public ulong CameraRevision { get; init; }
    public ulong BaseViewportRevision { get; init; }
    public ulong ViewportRevision { get; init; }
    public IReadOnlyList<NativeMeshSubmeshData> Submeshes { get; init; } = [];
    public IReadOnlyList<NativeMeshSelectionData> Selections { get; init; } = [];
    public IReadOnlyList<NativeMeshProjectionData> Projections { get; init; } = [];
    public double[]? WorldViewProjection { get; init; }
    public double ViewportWidth { get; init; }
    public double ViewportHeight { get; init; }
}

internal sealed class NativeMeshInteractionGestureRequest
{
    public ulong GestureId { get; init; }
    public ulong MeshRevision { get; init; }
    public ulong SelectionRevision { get; init; }
    public ulong TopologyGeneration { get; init; }
    public ulong CameraRevision { get; init; }
    public ulong ViewportRevision { get; init; }
    public NativeMeshInteractionTool Tool { get; init; }
    public NativeMeshSelectionTarget SelectionTarget { get; init; } = NativeMeshSelectionTarget.Vertex;
    public NativeMeshSelectionShape SelectionShape { get; init; } = NativeMeshSelectionShape.Brush;
    public NativeMeshSelectionOperation SelectionOperation { get; init; } = NativeMeshSelectionOperation.Replace;
    public bool XRay { get; init; }
    public double StartX { get; init; }
    public double StartY { get; init; }
    public double CurrentX { get; init; }
    public double CurrentY { get; init; }
    public double RadiusPixels { get; init; }
    public double Strength { get; init; }
    public double Pressure { get; init; }
    public double DeltaX { get; init; }
    public double DeltaY { get; init; }
    public double DeltaZ { get; init; }
    public double[] PointsXy { get; init; } = [];
}

internal sealed record NativeMeshInteractionPrepareSnapshotRequest(
    ulong MeshRevision,
    ulong SelectionRevision,
    ulong TopologyGeneration,
    ulong CameraRevision,
    ulong ViewportRevision,
    ulong VisiblePartsRevision,
    ulong ModelTransformRevision,
    bool XRay
);

internal sealed record NativeMeshInteractionAuthorityRequest(
    ulong GestureId,
    NativeMeshInteractionAuthorityAction Action,
    ulong BaseMeshRevision,
    ulong MeshRevision,
    ulong BaseSelectionRevision,
    ulong SelectionRevision,
    ulong BaseTopologyGeneration,
    ulong TopologyGeneration
);

internal sealed record NativeMeshDirtyRange(
    int SubmeshIndex,
    uint FirstVertex,
    uint VertexCount,
    ulong MeshRevision,
    ulong TopologyGeneration,
    ulong InteractionGeneration
);

internal sealed record NativeMeshSelectionChange(
    int SubmeshIndex,
    NativeMeshSelectionTarget Target,
    uint FirstElement,
    uint SecondElement,
    uint ElementCount,
    bool Selected,
    ulong SelectionRevision,
    ulong InteractionGeneration
);

internal sealed record NativeMeshInteractionResult(
    NativeMeshInteractionStatus Status,
    NativeMeshInteractionOperatorState OperatorState,
    ulong SessionHandle,
    ulong GestureId,
    ulong MeshRevision,
    ulong SelectionRevision,
    ulong TopologyGeneration,
    ulong CameraRevision,
    ulong ViewportRevision,
    ulong InteractionGeneration,
    uint RequiredDirtyRangeCount,
    IReadOnlyList<NativeMeshDirtyRange> DirtyRanges,
    uint RequiredSelectionChangeCount,
    IReadOnlyList<NativeMeshSelectionChange> SelectionChanges,
    string Message
)
{
    public bool IsSuccess => Status == NativeMeshInteractionStatus.Ok;
}

internal sealed record NativeMeshInteractionOpenOutcome(
    NativeMeshInteractionSession? Session,
    NativeMeshInteractionResult Result
);

internal sealed record NativeMeshVertexReadOutcome(
    double[] PositionsXyz,
    uint WrittenVertexCount,
    NativeMeshInteractionResult Result
);

internal sealed record NativeMeshInteractionDiagnostics(
    string LibraryPath,
    string LibrarySha256,
    uint AbiVersion,
    string Contract,
    string Backend,
    string HeaderSha256,
    ReadOnlyDictionary<NativeMeshInteractionStructId, uint> StructSizes
);
