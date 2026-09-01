namespace Cdmw.MeshEditorExperiment;

internal sealed unsafe class NativeMeshInteractionSession : IDisposable
{
    private enum GestureCall
    {
        Begin,
        Update,
        End,
        Cancel,
    }

    private readonly object _callGate = new();
    private readonly NativeMeshInteractionAbi _owner;
    private readonly NativeMeshInteractionResultBuffer _resultBuffer;
    private bool _closed;

    internal NativeMeshInteractionSession(
        NativeMeshInteractionAbi owner,
        ulong sessionHandle,
        NativeMeshInteractionResultBuffer resultBuffer
    )
    {
        _owner = owner;
        SessionHandle = sessionHandle;
        _resultBuffer = resultBuffer;
    }

    internal ulong SessionHandle { get; }
    internal NativeMeshInteractionDiagnostics Diagnostics => _owner.Diagnostics;

    internal NativeMeshInteractionResult Sync(NativeMeshInteractionSyncRequest value)
    {
        ArgumentNullException.ThrowIfNull(value);
        lock (_callGate)
        {
            EnsureOpen();
            using var pins = new NativeMeshPinnedInputs();
            bool meshRequested = value.Flags.HasFlag(NativeMeshInteractionSyncFlags.Mesh);
            bool selectionRequested = value.Flags.HasFlag(NativeMeshInteractionSyncFlags.Selection);
            bool cameraRequested = value.Flags.HasFlag(NativeMeshInteractionSyncFlags.Camera);
            NativeMeshSubmeshV1[] submeshes = meshRequested
                ? NativeMeshInteractionMarshaller.CreateSubmeshes(value.Submeshes, pins)
                : [];
            NativeMeshSelectionV1[] selections = selectionRequested
                ? NativeMeshInteractionMarshaller.CreateSelections(value.Selections, pins)
                : [];
            NativeMeshProjectionV1[] projections = cameraRequested
                ? NativeMeshInteractionMarshaller.CreateProjections(value.Projections)
                : [];
            if (meshRequested)
            {
                _resultBuffer.EnsureFor(value.Submeshes);
            }
            fixed (NativeMeshSubmeshV1* submeshPointer = submeshes)
            fixed (NativeMeshSelectionV1* selectionPointer = selections)
            fixed (NativeMeshProjectionV1* projectionPointer = projections)
            {
                NativeMeshInteractionSyncV1 request = CreateSyncRequest(
                    SessionHandle,
                    value,
                    (nint)submeshPointer,
                    checked((uint)submeshes.Length),
                    (nint)selectionPointer,
                    checked((uint)selections.Length),
                    (nint)projectionPointer,
                    checked((uint)projections.Length)
                );
                return _owner.Sync(ref request, _resultBuffer);
            }
        }
    }

    internal NativeMeshInteractionResult Begin(NativeMeshInteractionGestureRequest value) =>
        InvokeGesture(value, GestureCall.Begin);

    internal NativeMeshInteractionResult PrepareSnapshot(
        NativeMeshInteractionPrepareSnapshotRequest value)
    {
        ArgumentNullException.ThrowIfNull(value);
        NativeMeshInteractionPrepareSnapshotV1 request;
        lock (_callGate)
        {
            EnsureOpen();
            request = new NativeMeshInteractionPrepareSnapshotV1
            {
                StructSize = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionPrepareSnapshotV1>(),
                StructVersion = NativeMeshInteractionAbi.AbiVersion,
                SessionHandle = SessionHandle,
                MeshRevision = value.MeshRevision,
                SelectionRevision = value.SelectionRevision,
                TopologyGeneration = value.TopologyGeneration,
                CameraRevision = value.CameraRevision,
                ViewportRevision = value.ViewportRevision,
                VisiblePartsRevision = value.VisiblePartsRevision,
                ModelTransformRevision = value.ModelTransformRevision,
                XRay = value.XRay ? 1u : 0u,
            };
        }
        var buffer = new NativeMeshInteractionResultBuffer(0, 0);
        return _owner.PrepareSnapshot(ref request, buffer);
    }

    internal NativeMeshInteractionResult Update(NativeMeshInteractionGestureRequest value) =>
        InvokeGesture(value, GestureCall.Update);

    internal NativeMeshInteractionResult End(NativeMeshInteractionGestureRequest value) =>
        InvokeGesture(value, GestureCall.End);

    internal NativeMeshInteractionResult Cancel(NativeMeshInteractionGestureRequest value) =>
        InvokeGesture(value, GestureCall.Cancel);

    internal NativeMeshInteractionResult ApplyAuthority(NativeMeshInteractionAuthorityRequest value)
    {
        ArgumentNullException.ThrowIfNull(value);
        lock (_callGate)
        {
            EnsureOpen();
            var request = new NativeMeshInteractionAuthorityV1
            {
                StructSize = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionAuthorityV1>(),
                StructVersion = NativeMeshInteractionAbi.AbiVersion,
                SessionHandle = SessionHandle,
                GestureId = value.GestureId,
                Action = (uint)value.Action,
                BaseMeshRevision = value.BaseMeshRevision,
                MeshRevision = value.MeshRevision,
                BaseSelectionRevision = value.BaseSelectionRevision,
                SelectionRevision = value.SelectionRevision,
                BaseTopologyGeneration = value.BaseTopologyGeneration,
                TopologyGeneration = value.TopologyGeneration,
            };
            return _owner.ApplyAuthoritative(ref request, _resultBuffer);
        }
    }

    internal NativeMeshVertexReadOutcome ReadVertices(int submeshIndex, uint firstVertex, uint vertexCount)
    {
        lock (_callGate)
        {
            EnsureOpen();
            int positionCapacity = checked((int)(checked((ulong)vertexCount * 3)));
            var positions = new double[positionCapacity];
            NativeMeshInteractionResult result;
            uint writtenVertexCount;
            fixed (double* positionPointer = positions)
            {
                var request = new NativeMeshInteractionVertexReadV1
                {
                    StructSize = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionVertexReadV1>(),
                    StructVersion = NativeMeshInteractionAbi.AbiVersion,
                    SessionHandle = SessionHandle,
                    SubmeshIndex = submeshIndex,
                    FirstVertex = firstVertex,
                    VertexCount = vertexCount,
                    PositionCapacity = checked((uint)positions.Length),
                    PositionsXyz = (nint)positionPointer,
                };
                result = _owner.ReadVertices(ref request, _resultBuffer);
                writtenVertexCount = request.WrittenVertexCount;
            }
            int writtenPositions = checked((int)(checked((ulong)writtenVertexCount * 3)));
            if (writtenPositions != positions.Length)
            {
                Array.Resize(ref positions, writtenPositions);
            }
            return new NativeMeshVertexReadOutcome(positions, writtenVertexCount, result);
        }
    }

    internal NativeMeshInteractionResult Close()
    {
        lock (_callGate)
        {
            EnsureOpen();
            var request = new NativeMeshInteractionSessionV1
            {
                StructSize = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionSessionV1>(),
                StructVersion = NativeMeshInteractionAbi.AbiVersion,
                SessionHandle = SessionHandle,
            };
            NativeMeshInteractionResult result = _owner.Close(ref request, _resultBuffer);
            if (result.Status is NativeMeshInteractionStatus.Ok or NativeMeshInteractionStatus.SessionNotFound)
            {
                _closed = true;
                _owner.ReleaseSession();
            }
            return result;
        }
    }

    public void Dispose()
    {
        lock (_callGate)
        {
            if (_closed)
            {
                return;
            }
            NativeMeshInteractionResult result = Close();
            if (result.Status is not NativeMeshInteractionStatus.Ok
                and not NativeMeshInteractionStatus.SessionNotFound)
            {
                throw new InvalidOperationException(
                    $"Native mesh interaction session {SessionHandle} could not close: {result.Status} {result.Message}"
                );
            }
        }
    }

    private NativeMeshInteractionResult InvokeGesture(
        NativeMeshInteractionGestureRequest value,
        GestureCall call
    )
    {
        ArgumentNullException.ThrowIfNull(value);
        lock (_callGate)
        {
            EnsureOpen();
            using var pins = new NativeMeshPinnedInputs();
            NativeMeshInteractionGestureV1 request =
                NativeMeshInteractionMarshaller.CreateGesture(SessionHandle, value, pins);
            return call switch
            {
                GestureCall.Begin => _owner.Begin(ref request, _resultBuffer),
                GestureCall.Update => _owner.Update(ref request, _resultBuffer),
                GestureCall.End => _owner.End(ref request, _resultBuffer),
                GestureCall.Cancel => _owner.Cancel(ref request, _resultBuffer),
                _ => throw new ArgumentOutOfRangeException(nameof(call)),
            };
        }
    }

    private static NativeMeshInteractionSyncV1 CreateSyncRequest(
        ulong sessionHandle,
        NativeMeshInteractionSyncRequest value,
        nint submeshes,
        uint submeshCount,
        nint selections,
        uint selectionCount,
        nint projections,
        uint projectionCount
    )
    {
        var request = new NativeMeshInteractionSyncV1
        {
            StructSize = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionSyncV1>(),
            StructVersion = NativeMeshInteractionAbi.AbiVersion,
            SessionHandle = sessionHandle,
            Flags = (uint)value.Flags,
            BaseMeshRevision = value.BaseMeshRevision,
            MeshRevision = value.MeshRevision,
            BaseSelectionRevision = value.BaseSelectionRevision,
            SelectionRevision = value.SelectionRevision,
            BaseTopologyGeneration = value.BaseTopologyGeneration,
            TopologyGeneration = value.TopologyGeneration,
            BaseCameraRevision = value.BaseCameraRevision,
            CameraRevision = value.CameraRevision,
            BaseViewportRevision = value.BaseViewportRevision,
            ViewportRevision = value.ViewportRevision,
            SubmeshCount = submeshCount,
            Submeshes = submeshes,
            SelectionCount = selectionCount,
            Selections = selections,
            ProjectionCount = projectionCount,
            Projections = projections,
            ViewportWidth = value.ViewportWidth,
            ViewportHeight = value.ViewportHeight,
        };
        if (value.Flags.HasFlag(NativeMeshInteractionSyncFlags.Camera))
        {
            if (value.WorldViewProjection is not { Length: 16 } matrix)
            {
                throw new ArgumentException("Camera synchronization requires a 4x4 matrix.", nameof(value));
            }
            for (int index = 0; index < 16; ++index)
            {
                request.WorldViewProjection[index] = matrix[index];
            }
        }
        return request;
    }

    private void EnsureOpen()
    {
        ObjectDisposedException.ThrowIf(_closed, this);
    }
}
