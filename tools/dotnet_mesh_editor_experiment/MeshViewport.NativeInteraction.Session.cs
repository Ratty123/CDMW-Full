using System.Security.Cryptography;
using System.Text;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    internal void ConfigureResidentNativeInteraction(
        string sessionId,
        long meshRevision,
        long selectionRevision,
        long topologyGeneration)
    {
        var normalized = (sessionId ?? string.Empty).Trim();
        if (normalized.Length == 0)
        {
            ReleaseResidentNativeInteraction();
            return;
        }
        _residentNativeRequired = true;
        var changedSession = !string.Equals(
            _residentNativeSessionId,
            normalized,
            StringComparison.Ordinal);
        _residentNativeSessionId = normalized;
        var targetMesh = checked((ulong)Math.Max(0, meshRevision));
        var targetSelection = checked((ulong)Math.Max(0, selectionRevision));
        var targetTopology = checked((ulong)Math.Max(0, topologyGeneration));
        if (changedSession || !ReferenceEquals(_residentNativeDocument, _document))
        {
            if (changedSession)
            {
                RejectAllResidentNativeTransactions("session_changed");
                _residentNativeTransactionSequence = 0;
                _residentNativeReplicationRejected = false;
            }
            CloseResidentNativeSession();
        }
        if (_residentNativeSession is null)
        {
            OpenResidentNativeSession(targetMesh, targetSelection, targetTopology);
            return;
        }
        if (ResidentNativeReplicationPending || _residentNativeAwaitingAuthority)
        {
            return;
        }
        if (!ResidentNativeReplicationPending)
        {
            _residentNativeDurableRevision = targetMesh;
            _residentNativeDurableSelectionRevision = targetSelection;
            _residentNativeDurableTopologyGeneration = targetTopology;
        }
        if (_residentNativeReplicationRejected
            && _residentNativeMeshRevision == targetMesh
            && _residentNativeSelectionRevision == targetSelection
            && _residentNativeTopologyGeneration == targetTopology)
        {
            _residentNativeReplicationRejected = false;
        }
        if (_residentNativeMeshRevision != targetMesh
            || _residentNativeSelectionRevision != targetSelection
            || _residentNativeTopologyGeneration != targetTopology)
        {
            SynchronizeResidentNativeDocument(targetMesh, targetSelection, targetTopology);
        }
    }

    internal void NotifyResidentNativeDocumentReplaced()
    {
        if (!_residentNativeRequired || _residentNativeSessionId.Length == 0)
        {
            return;
        }
        var mesh = _residentNativeMeshRevision;
        var selection = _residentNativeSelectionRevision;
        var topology = _residentNativeTopologyGeneration;
        CloseResidentNativeSession();
        OpenResidentNativeSession(mesh, selection, topology);
    }

    internal void ReleaseResidentNativeInteraction()
    {
        RejectAllResidentNativeTransactions("session_released");
        CloseResidentNativeSession();
        _residentNativeAbi?.Dispose();
        _residentNativeAbi = null;
        _residentNativeRequired = false;
        _residentNativeSessionId = string.Empty;
        _residentNativeFailure = string.Empty;
        _residentNativeReplicationRejected = false;
    }

    private void OpenResidentNativeSession(
        ulong meshRevision,
        ulong selectionRevision,
        ulong topologyGeneration)
    {
        try
        {
            _residentNativeAbi ??= NativeMeshInteractionAbi.LoadFromApplicationDirectory();
            var outcome = _residentNativeAbi.Open(new NativeMeshInteractionOpenRequest(
                ResidentSessionKey(_residentNativeSessionId),
                meshRevision,
                selectionRevision,
                topologyGeneration,
                0,
                0,
                ResidentNativeSubmeshes()));
            if (outcome.Session is null || !outcome.Result.IsSuccess)
            {
                throw new InvalidOperationException(
                    $"Native resident session open failed: {outcome.Result.Status} {outcome.Result.Message}");
            }
            _residentNativeSession = outcome.Session;
            _residentNativeDocument = _document;
            _residentNativeMeshRevision = meshRevision;
            if (!ResidentNativeReplicationPending)
            {
                _residentNativeDurableRevision = meshRevision;
                _residentNativeDurableSelectionRevision = selectionRevision;
                _residentNativeDurableTopologyGeneration = topologyGeneration;
            }
            _residentNativeSelectionRevision = selectionRevision;
            _residentNativeTopologyGeneration = topologyGeneration;
            _residentNativeCameraRevision = 0;
            _residentNativeViewportRevision = 0;
            _residentNativeVisiblePartsRevision = 0;
            _residentNativeModelTransformRevision = 0;
            _residentNativeVisibleParts = [];
            _residentNativeModelTransforms = [];
            _residentNativeCameraValid = false;
            _residentNativeFailure = string.Empty;
            SynchronizeResidentNativeSelection(expandSelectedParts: false);
            EnsureResidentNativePresentationState();
        }
        catch (Exception ex)
        {
            CloseResidentNativeSession();
            _residentNativeFailure = ex.Message;
            StatusRequested?.Invoke($"Mesh Editor native interaction unavailable: {ex.Message}");
        }
    }

    private void SynchronizeResidentNativeDocument(
        ulong meshRevision,
        ulong selectionRevision,
        ulong topologyGeneration)
    {
        var session = RequireResidentNativeSession();
        var result = session.Sync(new NativeMeshInteractionSyncRequest
        {
            Flags = NativeMeshInteractionSyncFlags.Mesh
                | NativeMeshInteractionSyncFlags.Selection
                | NativeMeshInteractionSyncFlags.Topology,
            BaseMeshRevision = _residentNativeMeshRevision,
            MeshRevision = meshRevision,
            BaseSelectionRevision = _residentNativeSelectionRevision,
            SelectionRevision = selectionRevision,
            BaseTopologyGeneration = _residentNativeTopologyGeneration,
            TopologyGeneration = topologyGeneration,
            BaseCameraRevision = _residentNativeCameraRevision,
            CameraRevision = _residentNativeCameraRevision,
            BaseViewportRevision = _residentNativeViewportRevision,
            ViewportRevision = _residentNativeViewportRevision,
            Submeshes = ResidentNativeSubmeshes(),
            Selections = ResidentNativeSelections(expandSelectedParts: false),
        });
        RequireResidentNativeSuccess(result, "document synchronization");
        _residentNativeDocument = _document;
        _residentNativeMeshRevision = meshRevision;
        _residentNativeSelectionRevision = selectionRevision;
        _residentNativeTopologyGeneration = topologyGeneration;
    }

    private void SynchronizeResidentNativeSelection(bool expandSelectedParts)
    {
        var session = RequireResidentNativeSession();
        var result = session.Sync(new NativeMeshInteractionSyncRequest
        {
            Flags = NativeMeshInteractionSyncFlags.Selection,
            BaseMeshRevision = _residentNativeMeshRevision,
            MeshRevision = _residentNativeMeshRevision,
            BaseSelectionRevision = _residentNativeSelectionRevision,
            SelectionRevision = _residentNativeSelectionRevision,
            BaseTopologyGeneration = _residentNativeTopologyGeneration,
            TopologyGeneration = _residentNativeTopologyGeneration,
            BaseCameraRevision = _residentNativeCameraRevision,
            CameraRevision = _residentNativeCameraRevision,
            BaseViewportRevision = _residentNativeViewportRevision,
            ViewportRevision = _residentNativeViewportRevision,
            Selections = ResidentNativeSelections(expandSelectedParts),
        });
        RequireResidentNativeSuccess(result, "selection synchronization");
    }

    private void EnsureResidentNativePresentationState()
    {
        var viewport = ActivePaneBounds();
        var size = new Size(Math.Max(1, viewport.Width), Math.Max(1, viewport.Height));
        var camera = CurrentCamera();
        var matrix = camera.WorldViewProjection;
        var visibleParts = VisibleEditableSubmeshIndices();
        var modelTransforms = ResidentNativeModelTransforms(visibleParts);
        var projections = ResidentNativeProjections(camera, visibleParts);
        var visiblePartsChanged = !_residentNativeCameraValid
            || !_residentNativeVisibleParts.SequenceEqual(visibleParts);
        var modelTransformsChanged = !_residentNativeCameraValid
            || !ResidentNativeProjectionsEqual(
                _residentNativeModelTransforms,
                modelTransforms);
        var cameraChanged = !_residentNativeCameraValid
            || !_residentNativeCameraMatrix.Equals(matrix)
            || !ResidentNativeProjectionsEqual(_residentNativeProjections, projections);
        var viewportChanged = !_residentNativeCameraValid || _residentNativeViewportSize != size;
        if (!cameraChanged && !viewportChanged)
        {
            QueueResidentNativeSnapshotPreparation();
            return;
        }
        var nextCamera = _residentNativeCameraRevision + (cameraChanged ? 1UL : 0UL);
        var nextViewport = _residentNativeViewportRevision + (viewportChanged ? 1UL : 0UL);
        var nextVisibleParts = _residentNativeVisiblePartsRevision
            + (visiblePartsChanged ? 1UL : 0UL);
        var nextModelTransform = _residentNativeModelTransformRevision
            + (modelTransformsChanged ? 1UL : 0UL);
        var flags = (cameraChanged ? NativeMeshInteractionSyncFlags.Camera : 0)
            | (viewportChanged ? NativeMeshInteractionSyncFlags.Viewport : 0);
        var result = RequireResidentNativeSession().Sync(new NativeMeshInteractionSyncRequest
        {
            Flags = flags,
            BaseMeshRevision = _residentNativeMeshRevision,
            MeshRevision = _residentNativeMeshRevision,
            BaseSelectionRevision = _residentNativeSelectionRevision,
            SelectionRevision = _residentNativeSelectionRevision,
            BaseTopologyGeneration = _residentNativeTopologyGeneration,
            TopologyGeneration = _residentNativeTopologyGeneration,
            BaseCameraRevision = _residentNativeCameraRevision,
            CameraRevision = nextCamera,
            BaseViewportRevision = _residentNativeViewportRevision,
            ViewportRevision = nextViewport,
            WorldViewProjection = MatrixRowMajorArray(matrix),
            Projections = projections,
            ViewportWidth = size.Width,
            ViewportHeight = size.Height,
        });
        RequireResidentNativeSuccess(result, "camera and viewport synchronization");
        _residentNativeCameraMatrix = matrix;
        _residentNativeProjections = projections;
        _residentNativeVisibleParts = visibleParts;
        _residentNativeModelTransforms = modelTransforms;
        _residentNativeViewportSize = size;
        _residentNativeCameraRevision = nextCamera;
        _residentNativeViewportRevision = nextViewport;
        _residentNativeVisiblePartsRevision = nextVisibleParts;
        _residentNativeModelTransformRevision = nextModelTransform;
        _residentNativeCameraValid = true;
        QueueResidentNativeSnapshotPreparation();
    }

    private void CloseResidentNativeSession()
    {
        InvalidateResidentNativeSnapshot();
        _residentNativeGesture = null;
        _residentNativeAwaitingAuthority = false;
        _residentNativePreviewPositions.Clear();
        if (_residentNativeSession is not null)
        {
            try { _residentNativeSession.Dispose(); }
            catch (Exception ex) { _residentNativeFailure = ex.Message; }
        }
        _residentNativeSession = null;
        _residentNativeDocument = null;
        _residentNativeCameraValid = false;
        _residentNativeProjections = [];
    }

    private NativeMeshInteractionSession RequireResidentNativeSession() =>
        _residentNativeSession
        ?? throw new InvalidOperationException(
            _residentNativeFailure.Length > 0
                ? _residentNativeFailure
                : "The packaged native interaction session is not open.");

    private static void RequireResidentNativeSuccess(
        NativeMeshInteractionResult result,
        string operation)
    {
        if (!result.IsSuccess)
        {
            throw new InvalidOperationException(
                $"Native {operation} failed: {result.Status} {result.Message}");
        }
    }

    private static ulong ResidentSessionKey(string sessionId)
    {
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(sessionId));
        var key = BitConverter.ToUInt64(digest, 0);
        return key != 0 ? key : throw new InvalidOperationException("Resident session identity hashed to zero.");
    }
}
