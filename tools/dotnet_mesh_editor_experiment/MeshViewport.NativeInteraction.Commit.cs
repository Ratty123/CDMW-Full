using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private void InitializeResidentNativeReplication()
    {
        _residentNativeReplicationTimer = new System.Windows.Forms.Timer { Interval = 1000 };
        _residentNativeReplicationTimer.Tick += OnResidentNativeReplicationTimer;
        _residentNativeReplicationTimer.Start();
    }

    private void DisposeResidentNativeReplication()
    {
        var timer = Interlocked.Exchange(ref _residentNativeReplicationTimer, null);
        if (timer is null)
        {
            return;
        }
        timer.Stop();
        timer.Tick -= OnResidentNativeReplicationTimer;
        timer.Dispose();
    }

    private void OnResidentNativeReplicationTimer(object? sender, EventArgs e)
    {
        var lease = _residentNativeTransactions.Values
            .Where(candidate => candidate.RequestId > 0 && candidate.PublishedUtc != default)
            .OrderBy(candidate => candidate.TransactionSequence)
            .FirstOrDefault();
        if (lease is null
            || lease.RetryCount > 0
            || DateTime.UtcNow - lease.PublishedUtc < TimeSpan.FromSeconds(5))
        {
            return;
        }
        lease.RetryCount++;
        lease.PublishedUtc = DateTime.UtcNow;
        var descriptor = lease.Descriptor(_residentNativeSessionId);
        descriptor["request_id"] = lease.RequestId;
        try
        {
            EditorEventRequested?.Invoke("resident_interaction_transaction", descriptor);
            StatusRequested?.Invoke("Syncing edits… Retrying the durable commit.");
        }
        catch (Exception ex)
        {
            StatusRequested?.Invoke($"Mesh edit sync retry failed: {ex.Message}");
        }
    }

    private bool CanQueueResidentNativeTransaction(ResidentInteractionTransactionLease lease)
    {
        return !_residentNativeReplicationRejected
            && _residentNativeTransactions.Count < ResidentNativeMaximumPendingTransactions
            && lease.Length <= ResidentNativeMaximumPendingBytes
            && _residentNativePendingTransactionBytes <= ResidentNativeMaximumPendingBytes - lease.Length;
    }

    private void CommitResidentNativeTransaction(ResidentInteractionTransactionLease lease)
    {
        var changedChannels = new Dictionary<int, MeshVertexChannelChanges>();
        foreach (var (submeshIndex, vertices) in lease.Geometry)
        {
            var submesh = _document.Submeshes[submeshIndex];
            var changedPositions = new int[vertices.Count];
            var offset = 0;
            foreach (var (vertexIndex, position) in vertices)
            {
                submesh.Vertices[checked((int)vertexIndex)] = new Vec3(
                    checked((float)position.X),
                    checked((float)position.Y),
                    checked((float)position.Z));
                changedPositions[offset++] = checked((int)vertexIndex);
            }
            var changedNormals = RecomputeResidentNativeNormals(submesh);
            changedChannels[submeshIndex] = new MeshVertexChannelChanges(
                changedPositions,
                changedNormals,
                Array.Empty<int>());
        }

        if (lease.Tool == NativeMeshInteractionTool.Select)
        {
            ReplaceSelectionMap(_selectedVertices, _provisionalSelectedVertices);
            ReplaceSelectionMap(_selectedFaces, _provisionalSelectedFaces);
            _selectedEdges.Clear();
            _selectedEdges.UnionWith(_provisionalSelectedEdges);
            _selectedSources.Clear();
            _selectedSources.UnionWith(_provisionalSelectedSources);
            if (!AcceptAuthoritativeSelection(0, checked((long)lease.TargetSelectionRevision)))
            {
                throw new InvalidOperationException("The local native selection revision was rejected.");
            }
        }

        var authority = RequireResidentNativeSession().ApplyAuthority(
            new NativeMeshInteractionAuthorityRequest(
                lease.GestureId,
                NativeMeshInteractionAuthorityAction.Accepted,
                lease.BaseMeshRevision,
                lease.TargetMeshRevision,
                lease.BaseSelectionRevision,
                lease.TargetSelectionRevision,
                lease.TopologyGeneration,
                lease.TopologyGeneration));
        RequireResidentNativeSuccess(authority, "local interaction acceptance");
        _residentNativeMeshRevision = lease.TargetMeshRevision;
        _residentNativeSelectionRevision = lease.TargetSelectionRevision;
        _residentNativeTransactionSequence = lease.TransactionSequence;
        _residentNativeAwaitingAuthority = false;

        if (changedChannels.Count > 0)
        {
            RefreshVertexGeometry(changedChannels);
        }
        _editOperators.ApplyAuthoritativeResult(lease.OperatorGestureId);
        ClearResidentNativePreview();
        _editOperators.CompleteRenderer(lease.OperatorGestureId);
        InvalidateResidentNativeSnapshot();
        QueueResidentNativeSnapshotPreparation();
    }

    private static int[] RecomputeResidentNativeNormals(ObjSubmesh submesh)
    {
        if (submesh.Vertices.Count == 0)
        {
            submesh.Normals.Clear();
            submesh.NormalsVertexAligned = true;
            return [];
        }
        var accumulated = new Vector3[submesh.Vertices.Count];
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length < 3)
            {
                continue;
            }
            var firstIndex = face.Corners[0].VertexIndex;
            if (firstIndex < 0 || firstIndex >= submesh.Vertices.Count)
            {
                continue;
            }
            var first = ResidentNormalVector(submesh.Vertices[firstIndex]);
            for (var cornerIndex = 1; cornerIndex + 1 < face.Corners.Length; cornerIndex++)
            {
                var secondIndex = face.Corners[cornerIndex].VertexIndex;
                var thirdIndex = face.Corners[cornerIndex + 1].VertexIndex;
                if (secondIndex < 0 || secondIndex >= submesh.Vertices.Count
                    || thirdIndex < 0 || thirdIndex >= submesh.Vertices.Count)
                {
                    continue;
                }
                var normal = Vector3.Cross(
                    ResidentNormalVector(submesh.Vertices[secondIndex]) - first,
                    ResidentNormalVector(submesh.Vertices[thirdIndex]) - first);
                if (normal.LengthSquared() <= 1e-20f)
                {
                    continue;
                }
                accumulated[firstIndex] += normal;
                accumulated[secondIndex] += normal;
                accumulated[thirdIndex] += normal;
            }
            for (var cornerIndex = 0; cornerIndex < face.Corners.Length; cornerIndex++)
            {
                var corner = face.Corners[cornerIndex];
                if (corner.VertexIndex >= 0 && corner.VertexIndex < submesh.Vertices.Count)
                {
                    face.Corners[cornerIndex] = corner with { NormalIndex = corner.VertexIndex };
                }
            }
        }
        submesh.Normals.Clear();
        submesh.Normals.AddRange(accumulated.Select(value =>
        {
            var normal = value.LengthSquared() > 1e-20f ? Vector3.Normalize(value) : Vector3.UnitZ;
            return new Vec3(normal.X, normal.Y, normal.Z);
        }));
        submesh.NormalsVertexAligned = true;
        return Enumerable.Range(0, submesh.Vertices.Count).ToArray();
    }

    private static Vector3 ResidentNormalVector(Vec3 value) => new(value.X, value.Y, value.Z);

    private void RestoreResidentNativeTransactionBaseline(ResidentInteractionTransactionLease lease)
    {
        var changed = new Dictionary<int, MeshVertexChannelChanges>();
        foreach (var (submeshIndex, vertices) in lease.BaselineGeometry)
        {
            var submesh = _document.Submeshes[submeshIndex];
            foreach (var (vertexIndex, position) in vertices)
            {
                submesh.Vertices[checked((int)vertexIndex)] = position;
            }
            changed[submeshIndex] = new MeshVertexChannelChanges(
                vertices.Keys.Select(index => checked((int)index)).ToArray(),
                RecomputeResidentNativeNormals(submesh),
                Array.Empty<int>());
        }
        RestoreResidentMutationSelection(lease.BaselineSelection);
        ClearProvisionalSelectionEcho();
        if (changed.Count > 0)
        {
            RefreshVertexGeometry(changed);
        }
    }
}
