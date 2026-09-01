using System.Runtime.InteropServices;

namespace Cdmw.MeshEditorExperiment;

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshSubmeshV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal int SubmeshIndex;
    internal uint VertexCount;
    internal nint PositionsXyz;
    internal nint NormalsXyz;
    internal uint TriangleCount;
    internal nint TriangleIndices;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshSelectionV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal int SubmeshIndex;
    internal uint VertexCount;
    internal nint VertexIndices;
    internal uint FaceCount;
    internal nint FaceIndices;
    internal uint EdgeCount;
    internal nint EdgeVertexPairs;
}

[StructLayout(LayoutKind.Sequential)]
internal unsafe struct NativeMeshProjectionV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal int SubmeshIndex;
    internal uint Reserved;
    internal fixed double WorldViewProjection[16];
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshInteractionOpenV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal ulong SessionKey;
    internal ulong MeshRevision;
    internal ulong SelectionRevision;
    internal ulong TopologyGeneration;
    internal ulong CameraRevision;
    internal ulong ViewportRevision;
    internal uint SubmeshCount;
    internal nint Submeshes;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshInteractionSessionV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal ulong SessionHandle;
}

[StructLayout(LayoutKind.Sequential)]
internal unsafe struct NativeMeshInteractionSyncV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal ulong SessionHandle;
    internal uint Flags;
    internal uint Reserved;
    internal ulong BaseMeshRevision;
    internal ulong MeshRevision;
    internal ulong BaseSelectionRevision;
    internal ulong SelectionRevision;
    internal ulong BaseTopologyGeneration;
    internal ulong TopologyGeneration;
    internal ulong BaseCameraRevision;
    internal ulong CameraRevision;
    internal ulong BaseViewportRevision;
    internal ulong ViewportRevision;
    internal uint SubmeshCount;
    internal nint Submeshes;
    internal uint SelectionCount;
    internal nint Selections;
    internal uint ProjectionCount;
    internal nint Projections;
    internal fixed double WorldViewProjection[16];
    internal double ViewportWidth;
    internal double ViewportHeight;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshInteractionGestureV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal ulong SessionHandle;
    internal ulong GestureId;
    internal ulong MeshRevision;
    internal ulong SelectionRevision;
    internal ulong TopologyGeneration;
    internal ulong CameraRevision;
    internal ulong ViewportRevision;
    internal uint Tool;
    internal uint SelectionTarget;
    internal uint SelectionShape;
    internal uint SelectionOperation;
    internal uint XRay;
    internal uint Reserved;
    internal double StartX;
    internal double StartY;
    internal double CurrentX;
    internal double CurrentY;
    internal double RadiusPixels;
    internal double Strength;
    internal double Pressure;
    internal double DeltaX;
    internal double DeltaY;
    internal double DeltaZ;
    internal uint PointCount;
    internal nint PointsXy;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshInteractionPrepareSnapshotV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal ulong SessionHandle;
    internal ulong MeshRevision;
    internal ulong SelectionRevision;
    internal ulong TopologyGeneration;
    internal ulong CameraRevision;
    internal ulong ViewportRevision;
    internal ulong VisiblePartsRevision;
    internal ulong ModelTransformRevision;
    internal uint XRay;
    internal uint Reserved;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshInteractionAuthorityV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal ulong SessionHandle;
    internal ulong GestureId;
    internal uint Action;
    internal uint Reserved;
    internal ulong BaseMeshRevision;
    internal ulong MeshRevision;
    internal ulong BaseSelectionRevision;
    internal ulong SelectionRevision;
    internal ulong BaseTopologyGeneration;
    internal ulong TopologyGeneration;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshInteractionVertexReadV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal ulong SessionHandle;
    internal int SubmeshIndex;
    internal uint FirstVertex;
    internal uint VertexCount;
    internal uint PositionCapacity;
    internal nint PositionsXyz;
    internal uint WrittenVertexCount;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshDirtyRangeV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal int SubmeshIndex;
    internal uint FirstVertex;
    internal uint VertexCount;
    internal ulong MeshRevision;
    internal ulong TopologyGeneration;
    internal ulong InteractionGeneration;
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeMeshSelectionChangeV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal int SubmeshIndex;
    internal uint Target;
    internal uint FirstElement;
    internal uint SecondElement;
    internal uint ElementCount;
    internal uint Selected;
    internal ulong SelectionRevision;
    internal ulong InteractionGeneration;
}

[StructLayout(LayoutKind.Sequential)]
internal unsafe struct NativeMeshInteractionResultV1
{
    internal uint StructSize;
    internal uint StructVersion;
    internal uint Status;
    internal uint OperatorState;
    internal ulong SessionHandle;
    internal ulong GestureId;
    internal ulong MeshRevision;
    internal ulong SelectionRevision;
    internal ulong TopologyGeneration;
    internal ulong CameraRevision;
    internal ulong ViewportRevision;
    internal ulong InteractionGeneration;
    internal uint DirtyRangeCapacity;
    internal nint DirtyRanges;
    internal uint DirtyRangeCount;
    internal uint SelectionChangeCapacity;
    internal nint SelectionChanges;
    internal uint SelectionChangeCount;
    internal fixed byte Message[256];
}
