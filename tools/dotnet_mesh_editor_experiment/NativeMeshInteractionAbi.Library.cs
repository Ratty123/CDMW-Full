using System.Collections.ObjectModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace Cdmw.MeshEditorExperiment;

internal sealed unsafe class NativeMeshInteractionAbi : IDisposable
{
    internal const uint AbiVersion = 1;
    internal const string DllFileName = "cdmw-mesh-core.dll";
    internal const string ExpectedContract = "cdmw_mesh_interaction_abi_v1";
    internal const string ExpectedBackend = "cdmw_mesh_core_0.1";
    internal const string ExpectedHeaderSha256 =
        "603044AF6B01430939112DA0CD173B15674E43B3E3BED92D67B55BB2D1A9840A";

    private readonly object _lifetimeGate = new();
    private readonly nint _libraryHandle;
    private readonly delegate* unmanaged[Cdecl]<uint> _getAbiVersion;
    private readonly delegate* unmanaged[Cdecl]<byte*> _getContract;
    private readonly delegate* unmanaged[Cdecl]<byte*> _getHeaderSha256;
    private readonly delegate* unmanaged[Cdecl]<byte*> _getBackend;
    private readonly delegate* unmanaged[Cdecl]<uint, uint> _getStructSize;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionOpenV1*, NativeMeshInteractionResultV1*, uint> _open;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionSessionV1*, NativeMeshInteractionResultV1*, uint> _close;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionSyncV1*, NativeMeshInteractionResultV1*, uint> _sync;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionPrepareSnapshotV1*, NativeMeshInteractionResultV1*, uint> _prepareSnapshot;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint> _begin;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint> _update;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint> _end;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint> _cancel;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionAuthorityV1*, NativeMeshInteractionResultV1*, uint> _applyAuthoritative;
    private readonly delegate* unmanaged[Cdecl]<NativeMeshInteractionVertexReadV1*, NativeMeshInteractionResultV1*, uint> _readVertices;
    private int _activeSessions;
    private int _activeCalls;
    private bool _disposeRequested;
    private bool _disposed;

    private NativeMeshInteractionAbi(nint libraryHandle, string libraryPath, string librarySha256)
    {
        _libraryHandle = libraryHandle;
        _getAbiVersion = (delegate* unmanaged[Cdecl]<uint>)GetExport("cdmw_mesh_interaction_abi_version");
        _getContract = (delegate* unmanaged[Cdecl]<byte*>)GetExport("cdmw_mesh_interaction_abi_contract");
        _getHeaderSha256 = (delegate* unmanaged[Cdecl]<byte*>)GetExport("cdmw_mesh_interaction_abi_header_sha256");
        _getBackend = (delegate* unmanaged[Cdecl]<byte*>)GetExport("cdmw_mesh_interaction_backend");
        _getStructSize = (delegate* unmanaged[Cdecl]<uint, uint>)GetExport("cdmw_mesh_interaction_struct_size");
        _open = (delegate* unmanaged[Cdecl]<NativeMeshInteractionOpenV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_open");
        _close = (delegate* unmanaged[Cdecl]<NativeMeshInteractionSessionV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_close");
        _sync = (delegate* unmanaged[Cdecl]<NativeMeshInteractionSyncV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_sync");
        _prepareSnapshot = (delegate* unmanaged[Cdecl]<NativeMeshInteractionPrepareSnapshotV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_prepare_snapshot_v1");
        _begin = (delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_begin");
        _update = (delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_update");
        _end = (delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_end");
        _cancel = (delegate* unmanaged[Cdecl]<NativeMeshInteractionGestureV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_cancel");
        _applyAuthoritative = (delegate* unmanaged[Cdecl]<NativeMeshInteractionAuthorityV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_apply_authoritative");
        _readVertices = (delegate* unmanaged[Cdecl]<NativeMeshInteractionVertexReadV1*, NativeMeshInteractionResultV1*, uint>)GetExport("cdmw_mesh_interaction_read_vertices");
        Diagnostics = ValidateContract(libraryPath, librarySha256);
    }

    internal NativeMeshInteractionDiagnostics Diagnostics { get; }

    internal static NativeMeshInteractionAbi LoadFromApplicationDirectory()
    {
        string libraryPath = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, DllFileName));
        if (!Path.IsPathFullyQualified(libraryPath))
        {
            throw new InvalidOperationException("The native mesh ABI path is not absolute.");
        }
        if (!File.Exists(libraryPath))
        {
            throw new DllNotFoundException($"Required native mesh ABI was not found at '{libraryPath}'.");
        }
        nint handle = NativeLibrary.Load(libraryPath);
        try
        {
            string librarySha256;
            using (FileStream stream = File.OpenRead(libraryPath))
            {
                librarySha256 = Convert.ToHexString(SHA256.HashData(stream));
            }
            return new NativeMeshInteractionAbi(handle, libraryPath, librarySha256);
        }
        catch
        {
            NativeLibrary.Free(handle);
            throw;
        }
    }

    internal NativeMeshInteractionOpenOutcome Open(NativeMeshInteractionOpenRequest value)
    {
        ArgumentNullException.ThrowIfNull(value);
        lock (_lifetimeGate)
        {
            ThrowIfDisposed();
            using var pins = new NativeMeshPinnedInputs();
            NativeMeshSubmeshV1[] submeshes = NativeMeshInteractionMarshaller.CreateSubmeshes(value.Submeshes, pins);
            (int dirtyCapacity, int selectionCapacity) =
                NativeMeshInteractionMarshaller.DescriptorCapacities(value.Submeshes);
            var buffer = new NativeMeshInteractionResultBuffer(dirtyCapacity, selectionCapacity);
            fixed (NativeMeshSubmeshV1* submeshPointer = submeshes)
            {
                var request = new NativeMeshInteractionOpenV1
                {
                    StructSize = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionOpenV1>(),
                    StructVersion = AbiVersion,
                    SessionKey = value.SessionKey,
                    MeshRevision = value.MeshRevision,
                    SelectionRevision = value.SelectionRevision,
                    TopologyGeneration = value.TopologyGeneration,
                    CameraRevision = value.CameraRevision,
                    ViewportRevision = value.ViewportRevision,
                    SubmeshCount = checked((uint)submeshes.Length),
                    Submeshes = (nint)submeshPointer,
                };
                NativeMeshInteractionResult result = InvokeUnchecked(ref request, buffer, _open);
                if (!result.IsSuccess)
                {
                    return new NativeMeshInteractionOpenOutcome(null, result);
                }
                if (result.SessionHandle == 0)
                {
                    throw new InvalidDataException("Native ABI opened a session without returning a handle.");
                }
                ++_activeSessions;
                var session = new NativeMeshInteractionSession(this, result.SessionHandle, buffer);
                return new NativeMeshInteractionOpenOutcome(session, result);
            }
        }
    }

    public void Dispose()
    {
        lock (_lifetimeGate)
        {
            if (_disposed)
            {
                return;
            }
            if (_activeSessions != 0)
            {
                throw new InvalidOperationException("Close every native mesh interaction session before unloading its DLL.");
            }
            if (_activeCalls != 0)
            {
                _disposeRequested = true;
                return;
            }
            CompleteDisposeLocked();
        }
    }

    internal NativeMeshInteractionResult Sync(
        ref NativeMeshInteractionSyncV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _sync);

    internal NativeMeshInteractionResult Begin(
        ref NativeMeshInteractionGestureV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _begin);

    internal NativeMeshInteractionResult PrepareSnapshot(
        ref NativeMeshInteractionPrepareSnapshotV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _prepareSnapshot);

    internal NativeMeshInteractionResult Update(
        ref NativeMeshInteractionGestureV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _update);

    internal NativeMeshInteractionResult End(
        ref NativeMeshInteractionGestureV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _end);

    internal NativeMeshInteractionResult Cancel(
        ref NativeMeshInteractionGestureV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _cancel);

    internal NativeMeshInteractionResult ApplyAuthoritative(
        ref NativeMeshInteractionAuthorityV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _applyAuthoritative);

    internal NativeMeshInteractionResult ReadVertices(
        ref NativeMeshInteractionVertexReadV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _readVertices);

    internal NativeMeshInteractionResult Close(
        ref NativeMeshInteractionSessionV1 request,
        NativeMeshInteractionResultBuffer buffer
    ) => Invoke(ref request, buffer, _close);

    internal void ReleaseSession()
    {
        lock (_lifetimeGate)
        {
            if (_activeSessions <= 0)
            {
                throw new InvalidDataException("Managed native mesh session accounting underflowed.");
            }
            --_activeSessions;
        }
    }

    private NativeMeshInteractionDiagnostics ValidateContract(string libraryPath, string librarySha256)
    {
        uint abiVersion = _getAbiVersion();
        string contract = ReadExportString(_getContract(), "cdmw_mesh_interaction_abi_contract");
        string backend = ReadExportString(_getBackend(), "cdmw_mesh_interaction_backend");
        string headerSha256 = ReadExportString(_getHeaderSha256(), "cdmw_mesh_interaction_abi_header_sha256");
        if (abiVersion != AbiVersion || !string.Equals(contract, ExpectedContract, StringComparison.Ordinal))
        {
            throw new InvalidDataException($"Native mesh ABI reports v{abiVersion} '{contract}', expected v{AbiVersion} '{ExpectedContract}'.");
        }
        if (!string.Equals(backend, ExpectedBackend, StringComparison.Ordinal))
        {
            throw new InvalidDataException($"Native mesh ABI backend is '{backend}', expected '{ExpectedBackend}'.");
        }
        if (!string.Equals(headerSha256, ExpectedHeaderSha256, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException($"Native mesh ABI header SHA-256 is '{headerSha256}', expected '{ExpectedHeaderSha256}'.");
        }
        var sizes = ValidateStructSizes();
        return new NativeMeshInteractionDiagnostics(
            libraryPath,
            librarySha256,
            abiVersion,
            contract,
            backend,
            headerSha256,
            new ReadOnlyDictionary<NativeMeshInteractionStructId, uint>(sizes)
        );
    }

    private Dictionary<NativeMeshInteractionStructId, uint> ValidateStructSizes()
    {
        var expected = new Dictionary<NativeMeshInteractionStructId, uint>
        {
            [NativeMeshInteractionStructId.SubmeshV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshSubmeshV1>(),
            [NativeMeshInteractionStructId.SelectionV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshSelectionV1>(),
            [NativeMeshInteractionStructId.OpenV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionOpenV1>(),
            [NativeMeshInteractionStructId.SessionV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionSessionV1>(),
            [NativeMeshInteractionStructId.SyncV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionSyncV1>(),
            [NativeMeshInteractionStructId.GestureV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionGestureV1>(),
            [NativeMeshInteractionStructId.AuthorityV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionAuthorityV1>(),
            [NativeMeshInteractionStructId.VertexReadV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionVertexReadV1>(),
            [NativeMeshInteractionStructId.DirtyRangeV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshDirtyRangeV1>(),
            [NativeMeshInteractionStructId.SelectionChangeV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshSelectionChangeV1>(),
            [NativeMeshInteractionStructId.ResultV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionResultV1>(),
            [NativeMeshInteractionStructId.ProjectionV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshProjectionV1>(),
            [NativeMeshInteractionStructId.PrepareSnapshotV1] = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionPrepareSnapshotV1>(),
        };
        foreach ((NativeMeshInteractionStructId id, uint managedSize) in expected)
        {
            uint nativeSize = _getStructSize((uint)id);
            if (nativeSize != managedSize)
            {
                throw new InvalidDataException($"Native mesh ABI struct {id} is {nativeSize} bytes; managed v1 expects {managedSize}.");
            }
        }
        return expected;
    }

    private NativeMeshInteractionResult Invoke<TRequest>(
        ref TRequest request,
        NativeMeshInteractionResultBuffer buffer,
        delegate* unmanaged[Cdecl]<TRequest*, NativeMeshInteractionResultV1*, uint> operation
    ) where TRequest : unmanaged
    {
        lock (_lifetimeGate)
        {
            ThrowIfDisposed();
            ++_activeCalls;
        }
        try
        {
            return InvokeUnchecked(ref request, buffer, operation);
        }
        finally
        {
            lock (_lifetimeGate)
            {
                --_activeCalls;
                if (_activeCalls == 0 && _activeSessions == 0 && _disposeRequested)
                {
                    CompleteDisposeLocked();
                }
            }
        }
    }

    private static NativeMeshInteractionResult InvokeUnchecked<TRequest>(
        ref TRequest request,
        NativeMeshInteractionResultBuffer buffer,
        delegate* unmanaged[Cdecl]<TRequest*, NativeMeshInteractionResultV1*, uint> operation
    ) where TRequest : unmanaged
    {
        fixed (TRequest* requestPointer = &request)
        fixed (NativeMeshDirtyRangeV1* dirtyPointer = buffer.DirtyRanges)
        fixed (NativeMeshSelectionChangeV1* selectionPointer = buffer.SelectionChanges)
        {
            var result = new NativeMeshInteractionResultV1
            {
                StructSize = NativeMeshInteractionMarshaller.SizeOf<NativeMeshInteractionResultV1>(),
                StructVersion = AbiVersion,
                DirtyRangeCapacity = checked((uint)buffer.DirtyRanges.Length),
                DirtyRanges = (nint)dirtyPointer,
                SelectionChangeCapacity = checked((uint)buffer.SelectionChanges.Length),
                SelectionChanges = (nint)selectionPointer,
            };
            uint status = operation(requestPointer, &result);
            return NativeMeshInteractionMarshaller.ConvertResult(status, ref result, buffer);
        }
    }

    private nint GetExport(string name) => NativeLibrary.GetExport(_libraryHandle, name);

    private static string ReadExportString(byte* value, string exportName)
    {
        if (value == null)
        {
            throw new InvalidDataException($"Native mesh ABI export '{exportName}' returned null.");
        }
        return Marshal.PtrToStringUTF8((nint)value)
            ?? throw new InvalidDataException($"Native mesh ABI export '{exportName}' is not UTF-8.");
    }

    private void ThrowIfDisposed()
    {
        ObjectDisposedException.ThrowIf(_disposed || _disposeRequested, this);
    }

    private void CompleteDisposeLocked()
    {
        NativeLibrary.Free(_libraryHandle);
        _disposed = true;
        _disposeRequested = false;
    }
}
