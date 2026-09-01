namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private void InitializeResidentNativeSnapshotPreparation()
    {
        _residentNativeSnapshotSyncTimer = new System.Windows.Forms.Timer { Interval = 30 };
        _residentNativeSnapshotSyncTimer.Tick += OnResidentNativeSnapshotSyncTimer;
    }

    private void DisposeResidentNativeSnapshotPreparation()
    {
        InvalidateResidentNativeSnapshot();
        var timer = Interlocked.Exchange(ref _residentNativeSnapshotSyncTimer, null);
        if (timer is null)
        {
            return;
        }
        timer.Stop();
        timer.Tick -= OnResidentNativeSnapshotSyncTimer;
        timer.Dispose();
    }

    private void ScheduleResidentNativeSnapshotPreparation()
    {
        if (!ResidentNativeInteractionReady || _residentNativeGesture is not null)
        {
            return;
        }
        _residentNativeSnapshotSyncTimer?.Stop();
        _residentNativeSnapshotSyncTimer?.Start();
    }

    /// <summary>
    /// Returns whether a native gesture can begin now. Presentation changes are
    /// synchronized first so the ready stamp cannot describe the previous
    /// camera or viewport. A cache miss keeps preparing in the background and
    /// the required resident path fails closed instead of starting a legacy
    /// provisional gesture that cannot become authoritative.
    /// </summary>
    private bool ResidentNativeSnapshotAvailableForInput()
    {
        if (!ResidentNativeInteractionReady || ResidentNativeReplicationBlocked)
        {
            return false;
        }
        // A view-state notification is already queued for the UI timer. Do not
        // repeat its full-mesh projection synchronization in mouse-down. The
        // caller reports preparation and leaves no provisional gesture open.
        if (_residentNativeSnapshotSyncTimer?.Enabled == true)
        {
            return false;
        }
        if (ResidentNativeSnapshotReady(ShowXRay))
        {
            return true;
        }
        QueueResidentNativeSnapshotPreparation();
        return false;
    }

    private void OnResidentNativeSnapshotSyncTimer(object? sender, EventArgs e)
    {
        _residentNativeSnapshotSyncTimer?.Stop();
        if (!ResidentNativeInteractionReady || _residentNativeGesture is not null)
        {
            return;
        }
        try
        {
            EnsureResidentNativePresentationState();
            QueueResidentNativeSnapshotPreparation();
        }
        catch (Exception ex)
        {
            _residentNativeFailure = ex.Message;
            StatusRequested?.Invoke($"Mesh Editor interaction preparation failed: {ex.Message}");
        }
    }

    private ResidentNativeSnapshotStamp CurrentResidentNativeSnapshotStamp(bool xray) => new(
        _residentNativeMeshRevision,
        _residentNativeTopologyGeneration,
        _residentNativeCameraRevision,
        _residentNativeViewportRevision,
        _residentNativeVisiblePartsRevision,
        _residentNativeModelTransformRevision,
        xray);

    private bool ResidentNativeSnapshotReady(bool xray) =>
        _residentNativeSnapshotReady == CurrentResidentNativeSnapshotStamp(xray);

    private void QueueResidentNativeSnapshotPreparation()
    {
        var session = _residentNativeSession;
        if (session is null || !_residentNativeCameraValid)
        {
            return;
        }
        var stamp = CurrentResidentNativeSnapshotStamp(ShowXRay);
        if (_residentNativeSnapshotReady == stamp
            || (_residentNativeSnapshotRequested == stamp
                && _residentNativeSnapshotTask is { IsCompleted: false }))
        {
            return;
        }
        var generation = Interlocked.Increment(ref _residentNativeSnapshotGeneration);
        _residentNativeSnapshotRequested = stamp;
        _residentNativeSnapshotReady = null;
        if (_residentNativeSnapshotTask is { IsCompleted: false })
        {
            _residentNativeSnapshotCancellation?.Cancel();
            return;
        }
        var previous = Interlocked.Exchange(
            ref _residentNativeSnapshotCancellation,
            new CancellationTokenSource());
        previous?.Cancel();
        previous?.Dispose();
        var cancellation = _residentNativeSnapshotCancellation!;
        var token = cancellation.Token;
        var request = new NativeMeshInteractionPrepareSnapshotRequest(
            stamp.MeshRevision,
            _residentNativeSelectionRevision,
            stamp.TopologyGeneration,
            stamp.CameraRevision,
            stamp.ViewportRevision,
            stamp.VisiblePartsRevision,
            stamp.ModelTransformRevision,
            stamp.XRay);
        var work = Task.Run(() =>
        {
            token.ThrowIfCancellationRequested();
            var result = session.PrepareSnapshot(request);
            token.ThrowIfCancellationRequested();
            return result;
        }, token);
        _residentNativeSnapshotTask = work;
        _ = work.ContinueWith(task =>
        {
            try
            {
                BeginInvoke((Action)(() => CompleteResidentNativeSnapshotPreparation(
                    task,
                    session,
                    stamp,
                    generation,
                    cancellation,
                    token)));
            }
            catch (Exception ex) when (ex is InvalidOperationException or ObjectDisposedException)
            {
                // The viewport closed while a stale preparation was returning.
                cancellation.Dispose();
            }
        }, CancellationToken.None, TaskContinuationOptions.None, TaskScheduler.Default);
    }

    private void CompleteResidentNativeSnapshotPreparation(
        Task<NativeMeshInteractionResult> task,
        NativeMeshInteractionSession session,
        ResidentNativeSnapshotStamp stamp,
        long generation,
        CancellationTokenSource cancellation,
        CancellationToken token)
    {
        if (ReferenceEquals(_residentNativeSnapshotTask, task))
        {
            _residentNativeSnapshotTask = null;
        }
        if (ReferenceEquals(_residentNativeSnapshotCancellation, cancellation))
        {
            _residentNativeSnapshotCancellation = null;
        }
        cancellation.Dispose();
        var stale = generation != _residentNativeSnapshotGeneration
            || token.IsCancellationRequested
            || !ReferenceEquals(session, _residentNativeSession)
            || _residentNativeSnapshotRequested != stamp;
        if (stale)
        {
            if (ResidentNativeInteractionReady
                && _residentNativeGesture is null
                && _residentNativeSnapshotRequested.HasValue)
            {
                QueueResidentNativeSnapshotPreparation();
            }
            return;
        }
        if (task.IsCanceled)
        {
            QueueResidentNativeSnapshotPreparation();
            return;
        }
        if (task.IsFaulted)
        {
            _residentNativeFailure = task.Exception?.GetBaseException().Message
                ?? "Native snapshot preparation failed.";
            StatusRequested?.Invoke($"Mesh Editor interaction preparation failed: {_residentNativeFailure}");
            return;
        }
        var result = task.Result;
        if (!result.IsSuccess)
        {
            if (result.Status != NativeMeshInteractionStatus.RevisionMismatch)
            {
                _residentNativeFailure = result.Message;
                StatusRequested?.Invoke($"Mesh Editor interaction preparation failed: {result.Message}");
            }
            return;
        }
        _residentNativeSnapshotReady = stamp;
        _residentNativeFailure = string.Empty;
        Invalidate();
    }

    private void InvalidateResidentNativeSnapshot()
    {
        Interlocked.Increment(ref _residentNativeSnapshotGeneration);
        var cancellation = Interlocked.Exchange(ref _residentNativeSnapshotCancellation, null);
        cancellation?.Cancel();
        if (_residentNativeSnapshotTask is null)
        {
            cancellation?.Dispose();
        }
        _residentNativeSnapshotRequested = null;
        _residentNativeSnapshotReady = null;
    }
}
