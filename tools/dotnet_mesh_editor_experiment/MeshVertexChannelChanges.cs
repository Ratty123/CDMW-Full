namespace Cdmw.MeshEditorExperiment;

internal sealed record MeshVertexChannelChanges(
    IReadOnlyCollection<int> Positions,
    IReadOnlyCollection<int> Normals,
    IReadOnlyCollection<int> Uvs)
{
    public static MeshVertexChannelChanges PositionsOnly(IReadOnlyCollection<int> positions)
    {
        return new MeshVertexChannelChanges(positions, Array.Empty<int>(), Array.Empty<int>());
    }
}
