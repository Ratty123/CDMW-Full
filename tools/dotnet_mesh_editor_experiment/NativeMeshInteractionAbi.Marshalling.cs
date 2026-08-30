using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace Cdmw.MeshEditorExperiment;

internal sealed class NativeMeshPinnedInputs : IDisposable
{
    private readonly List<GCHandle> _handles = [];

    internal nint Pin(Array values)
    {
        if (values.Length == 0)
        {
            return nint.Zero;
        }
        GCHandle handle = GCHandle.Alloc(values, GCHandleType.Pinned);
        _handles.Add(handle);
        return handle.AddrOfPinnedObject();
    }

    public void Dispose()
    {
        for (int index = _handles.Count - 1; index >= 0; --index)
        {
            _handles[index].Free();
        }
        _handles.Clear();
    }
}

internal sealed class NativeMeshInteractionResultBuffer
{
    private const int MinimumCapacity = 64;
    private NativeMeshDirtyRangeV1[] _dirtyRanges;
    private NativeMeshSelectionChangeV1[] _selectionChanges;

    internal NativeMeshInteractionResultBuffer(int dirtyCapacity, int selectionCapacity)
    {
        _dirtyRanges = new NativeMeshDirtyRangeV1[Math.Max(MinimumCapacity, dirtyCapacity)];
        _selectionChanges = new NativeMeshSelectionChangeV1[Math.Max(MinimumCapacity, selectionCapacity)];
    }

    internal NativeMeshDirtyRangeV1[] DirtyRanges => _dirtyRanges;
    internal NativeMeshSelectionChangeV1[] SelectionChanges => _selectionChanges;

    internal void EnsureFor(IReadOnlyList<NativeMeshSubmeshData> submeshes)
    {
        (int dirtyCapacity, int selectionCapacity) =
            NativeMeshInteractionMarshaller.DescriptorCapacities(submeshes);
        if (DirtyRanges.Length < dirtyCapacity)
        {
            Array.Resize(ref _dirtyRanges, dirtyCapacity);
        }
        if (SelectionChanges.Length < selectionCapacity)
        {
            Array.Resize(ref _selectionChanges, selectionCapacity);
        }
    }
}

internal static unsafe class NativeMeshInteractionMarshaller
{
    internal static NativeMeshSubmeshV1[] CreateSubmeshes(
        IReadOnlyList<NativeMeshSubmeshData> values,
        NativeMeshPinnedInputs pins
    )
    {
        ArgumentNullException.ThrowIfNull(values);
        if (values.Count == 0)
        {
            throw new ArgumentException("At least one submesh is required.", nameof(values));
        }
        var native = new NativeMeshSubmeshV1[values.Count];
        for (int index = 0; index < values.Count; ++index)
        {
            NativeMeshSubmeshData value = values[index]
                ?? throw new ArgumentException("Submesh entries cannot be null.", nameof(values));
            ValidateSubmeshBuffers(value);
            native[index] = new NativeMeshSubmeshV1
            {
                StructSize = SizeOf<NativeMeshSubmeshV1>(),
                StructVersion = NativeMeshInteractionAbi.AbiVersion,
                SubmeshIndex = value.SubmeshIndex,
                VertexCount = checked((uint)(value.PositionsXyz.Length / 3)),
                PositionsXyz = pins.Pin(value.PositionsXyz),
                NormalsXyz = value.NormalsXyz is { Length: > 0 } normals ? pins.Pin(normals) : nint.Zero,
                TriangleCount = checked((uint)(value.TriangleIndices.Length / 3)),
                TriangleIndices = pins.Pin(value.TriangleIndices),
            };
        }
        return native;
    }

    internal static NativeMeshSelectionV1[] CreateSelections(
        IReadOnlyList<NativeMeshSelectionData> values,
        NativeMeshPinnedInputs pins
    )
    {
        ArgumentNullException.ThrowIfNull(values);
        var native = new NativeMeshSelectionV1[values.Count];
        for (int index = 0; index < values.Count; ++index)
        {
            NativeMeshSelectionData value = values[index]
                ?? throw new ArgumentException("Selection entries cannot be null.", nameof(values));
            ValidateSelectionBuffers(value);
            native[index] = new NativeMeshSelectionV1
            {
                StructSize = SizeOf<NativeMeshSelectionV1>(),
                StructVersion = NativeMeshInteractionAbi.AbiVersion,
                SubmeshIndex = value.SubmeshIndex,
                VertexCount = checked((uint)value.VertexIndices.Length),
                VertexIndices = pins.Pin(value.VertexIndices),
                FaceCount = checked((uint)value.FaceIndices.Length),
                FaceIndices = pins.Pin(value.FaceIndices),
                EdgeCount = checked((uint)(value.EdgeVertexPairs.Length / 2)),
                EdgeVertexPairs = pins.Pin(value.EdgeVertexPairs),
            };
        }
        return native;
    }

    internal static NativeMeshProjectionV1[] CreateProjections(
        IReadOnlyList<NativeMeshProjectionData> values
    )
    {
        ArgumentNullException.ThrowIfNull(values);
        var native = new NativeMeshProjectionV1[values.Count];
        var indices = new HashSet<int>();
        for (int index = 0; index < values.Count; ++index)
        {
            NativeMeshProjectionData value = values[index]
                ?? throw new ArgumentException("Projection entries cannot be null.", nameof(values));
            if (value.SubmeshIndex < 0 || !indices.Add(value.SubmeshIndex))
            {
                throw new ArgumentException("Projection submesh indices must be non-negative and unique.", nameof(values));
            }
            if (value.WorldViewProjection is not { Length: 16 } matrix
                || matrix.Any(item => !double.IsFinite(item)))
            {
                throw new ArgumentException("Projection entries require a finite 4x4 matrix.", nameof(values));
            }
            var item = new NativeMeshProjectionV1
            {
                StructSize = SizeOf<NativeMeshProjectionV1>(),
                StructVersion = NativeMeshInteractionAbi.AbiVersion,
                SubmeshIndex = value.SubmeshIndex,
            };
            for (int element = 0; element < 16; ++element)
            {
                item.WorldViewProjection[element] = matrix[element];
            }
            native[index] = item;
        }
        return native;
    }

    internal static (int DirtyCapacity, int SelectionCapacity) DescriptorCapacities(
        IReadOnlyList<NativeMeshSubmeshData> submeshes
    )
    {
        ArgumentNullException.ThrowIfNull(submeshes);
        long dirty = 0;
        long selection = 0;
        foreach (NativeMeshSubmeshData submesh in submeshes)
        {
            ValidateSubmeshBuffers(submesh);
            long vertices = submesh.PositionsXyz.LongLength / 3;
            long triangles = submesh.TriangleIndices.LongLength / 3;
            dirty = checked(dirty + vertices);
            selection = checked(selection + vertices + (triangles * 4));
        }
        return (CheckedArrayCapacity(dirty), CheckedArrayCapacity(selection));
    }

    internal static NativeMeshInteractionGestureV1 CreateGesture(
        ulong sessionHandle,
        NativeMeshInteractionGestureRequest value,
        NativeMeshPinnedInputs pins
    )
    {
        ArgumentNullException.ThrowIfNull(value);
        ArgumentNullException.ThrowIfNull(value.PointsXy);
        if ((value.PointsXy.Length & 1) != 0)
        {
            throw new ArgumentException("Gesture points must contain x/y pairs.", nameof(value));
        }
        return new NativeMeshInteractionGestureV1
        {
            StructSize = SizeOf<NativeMeshInteractionGestureV1>(),
            StructVersion = NativeMeshInteractionAbi.AbiVersion,
            SessionHandle = sessionHandle,
            GestureId = value.GestureId,
            MeshRevision = value.MeshRevision,
            SelectionRevision = value.SelectionRevision,
            TopologyGeneration = value.TopologyGeneration,
            CameraRevision = value.CameraRevision,
            ViewportRevision = value.ViewportRevision,
            Tool = (uint)value.Tool,
            SelectionTarget = (uint)value.SelectionTarget,
            SelectionShape = (uint)value.SelectionShape,
            SelectionOperation = (uint)value.SelectionOperation,
            XRay = value.XRay ? 1u : 0u,
            StartX = value.StartX,
            StartY = value.StartY,
            CurrentX = value.CurrentX,
            CurrentY = value.CurrentY,
            RadiusPixels = value.RadiusPixels,
            Strength = value.Strength,
            Pressure = value.Pressure,
            DeltaX = value.DeltaX,
            DeltaY = value.DeltaY,
            DeltaZ = value.DeltaZ,
            PointCount = checked((uint)(value.PointsXy.Length / 2)),
            PointsXy = pins.Pin(value.PointsXy),
        };
    }

    internal static NativeMeshInteractionResult ConvertResult(
        uint returnStatus,
        ref NativeMeshInteractionResultV1 native,
        NativeMeshInteractionResultBuffer buffer
    )
    {
        if (returnStatus != native.Status)
        {
            throw new InvalidDataException(
                $"Native ABI return status {returnStatus} disagrees with result status {native.Status}."
            );
        }
        NativeMeshDirtyRange[] dirty = CopyDirtyRanges(native, buffer.DirtyRanges);
        NativeMeshSelectionChange[] changes = CopySelectionChanges(native, buffer.SelectionChanges);
        return new NativeMeshInteractionResult(
            (NativeMeshInteractionStatus)returnStatus,
            (NativeMeshInteractionOperatorState)native.OperatorState,
            native.SessionHandle,
            native.GestureId,
            native.MeshRevision,
            native.SelectionRevision,
            native.TopologyGeneration,
            native.CameraRevision,
            native.ViewportRevision,
            native.InteractionGeneration,
            native.DirtyRangeCount,
            dirty,
            native.SelectionChangeCount,
            changes,
            ReadMessage(ref native)
        );
    }

    internal static uint SizeOf<T>() where T : unmanaged => checked((uint)Marshal.SizeOf<T>());

    private static void ValidateSubmeshBuffers(NativeMeshSubmeshData value)
    {
        ArgumentNullException.ThrowIfNull(value);
        ArgumentNullException.ThrowIfNull(value.PositionsXyz);
        ArgumentNullException.ThrowIfNull(value.TriangleIndices);
        if (value.PositionsXyz.Length == 0 || value.PositionsXyz.Length % 3 != 0)
        {
            throw new ArgumentException("Submesh positions must contain complete xyz triples.", nameof(value));
        }
        if (value.NormalsXyz is { Length: > 0 } normals && normals.Length != value.PositionsXyz.Length)
        {
            throw new ArgumentException("Submesh normals must match the position buffer length.", nameof(value));
        }
        if (value.TriangleIndices.Length % 3 != 0)
        {
            throw new ArgumentException("Triangle indices must contain complete triples.", nameof(value));
        }
    }

    private static void ValidateSelectionBuffers(NativeMeshSelectionData value)
    {
        ArgumentNullException.ThrowIfNull(value.VertexIndices);
        ArgumentNullException.ThrowIfNull(value.FaceIndices);
        ArgumentNullException.ThrowIfNull(value.EdgeVertexPairs);
        if ((value.EdgeVertexPairs.Length & 1) != 0)
        {
            throw new ArgumentException("Selection edges must contain vertex pairs.", nameof(value));
        }
    }

    private static int CheckedArrayCapacity(long value)
    {
        if (value > Array.MaxLength)
        {
            throw new ArgumentOutOfRangeException(nameof(value), "Mesh descriptor capacity exceeds managed array limits.");
        }
        return checked((int)value);
    }

    private static NativeMeshDirtyRange[] CopyDirtyRanges(
        NativeMeshInteractionResultV1 native,
        NativeMeshDirtyRangeV1[] source
    )
    {
        int count = checked((int)Math.Min(native.DirtyRangeCount, (uint)source.Length));
        var result = new NativeMeshDirtyRange[count];
        for (int index = 0; index < count; ++index)
        {
            NativeMeshDirtyRangeV1 value = source[index];
            ValidateDescriptor(value.StructSize, value.StructVersion, SizeOf<NativeMeshDirtyRangeV1>());
            result[index] = new NativeMeshDirtyRange(
                value.SubmeshIndex,
                value.FirstVertex,
                value.VertexCount,
                value.MeshRevision,
                value.TopologyGeneration,
                value.InteractionGeneration
            );
        }
        return result;
    }

    private static NativeMeshSelectionChange[] CopySelectionChanges(
        NativeMeshInteractionResultV1 native,
        NativeMeshSelectionChangeV1[] source
    )
    {
        int count = checked((int)Math.Min(native.SelectionChangeCount, (uint)source.Length));
        var result = new NativeMeshSelectionChange[count];
        for (int index = 0; index < count; ++index)
        {
            NativeMeshSelectionChangeV1 value = source[index];
            ValidateDescriptor(value.StructSize, value.StructVersion, SizeOf<NativeMeshSelectionChangeV1>());
            result[index] = new NativeMeshSelectionChange(
                value.SubmeshIndex,
                (NativeMeshSelectionTarget)value.Target,
                value.FirstElement,
                value.SecondElement,
                value.ElementCount,
                value.Selected != 0,
                value.SelectionRevision,
                value.InteractionGeneration
            );
        }
        return result;
    }

    private static void ValidateDescriptor(uint size, uint version, uint expectedSize)
    {
        if (size != expectedSize || version != NativeMeshInteractionAbi.AbiVersion)
        {
            throw new InvalidDataException(
                $"Native result descriptor header is {size}/v{version}; expected {expectedSize}/v{NativeMeshInteractionAbi.AbiVersion}."
            );
        }
    }

    private static string ReadMessage(ref NativeMeshInteractionResultV1 native)
    {
        fixed (byte* pointer = native.Message)
        {
            int length = 0;
            while (length < 256 && pointer[length] != 0)
            {
                ++length;
            }
            return Encoding.UTF8.GetString(pointer, length);
        }
    }
}
