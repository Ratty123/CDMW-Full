namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// When a resident helper may reveal the scene it is holding.
/// </summary>
/// <remarks>
/// A prewarm launch starts the helper on a procedural placeholder so the
/// process, JIT and D3D11 device are warm before the first real request. Every
/// reveal on the start-up path is already suppressed for one (<c>--prewarm</c>),
/// but <c>ActivateResidentViewport</c> reveals whatever scene happens to be
/// resident, and its callers — an <c>activate_request</c> and the two deferred
/// activations after a material sync — cannot see what that is. A host that asks
/// at the wrong moment therefore put the warm-up triangle in the pane at full
/// size until the real model replaced it. The helper is the only party that
/// knows what it is actually rendering, so the decision belongs here rather than
/// in host-side sequencing spread across its callers.
/// </remarks>
internal static class ResidentActivationContract
{
    public static bool MatchesAcceptedPackageGeneration(
        long activationPackageGeneration,
        long acceptedPackageGeneration)
    {
        // The command-line package predates resident package generations, so
        // zero accepted generations permit its first activation. Once a
        // package_load_request is accepted, only that exact generation may
        // reveal; the reader-thread generation fence cannot be overtaken by
        // older activate requests already queued for the UI thread.
        return acceptedPackageGeneration <= 0
            || (activationPackageGeneration > 0
                && activationPackageGeneration == acceptedPackageGeneration);
    }

    public static bool MatchesPendingMaterialSync(
        bool waiting,
        long pendingGeneration,
        long completedGeneration,
        string pendingSignature,
        string completedSignature)
    {
        return waiting
            && pendingGeneration > 0
            && completedGeneration == pendingGeneration
            && !string.IsNullOrWhiteSpace(pendingSignature)
            && string.Equals(pendingSignature, completedSignature, StringComparison.Ordinal);
    }

    /// <summary>
    /// True when activation must be refused because the only scene this helper
    /// has ever been given is the prewarm placeholder.
    /// </summary>
    /// <param name="prewarmLaunch">Whether the process was started with <c>--prewarm</c>.</param>
    /// <param name="residentPackageLoadCount">Resident packages applied so far.</param>
    public static bool ShouldDeferActivation(bool prewarmLaunch, long residentPackageLoadCount)
    {
        return prewarmLaunch && residentPackageLoadCount <= 0;
    }
}
