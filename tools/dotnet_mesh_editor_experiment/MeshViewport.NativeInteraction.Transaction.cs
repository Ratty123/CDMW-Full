using System.IO;
using System.Text;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private ResidentInteractionTransactionLease? CreateResidentNativeTransaction(
        ResidentNativeGesture gesture,
        NativeMeshInteractionResult result)
    {
        var geometry = gesture.Tool == NativeMeshInteractionTool.Select
            ? new SortedDictionary<int, SortedDictionary<uint, (double X, double Y, double Z)>>()
            : ResidentNativeGeometryPayload(result.DirtyRanges);
        var selection = gesture.Tool == NativeMeshInteractionTool.Select
            ? result.SelectionChanges.ToArray()
            : [];
        if (geometry.Count == 0 && selection.Length == 0)
        {
            return null;
        }
        var targetMesh = checked(_residentNativeMeshRevision + 1);
        var targetSelection = checked(
            _residentNativeSelectionRevision
            + (gesture.Tool == NativeMeshInteractionTool.Select ? 1UL : 0UL));
        var payload = SerializeResidentNativeTransaction(
            gesture,
            geometry,
            selection,
            targetMesh,
            targetSelection);
        return ResidentInteractionTransactionLease.Create(
            payload,
            gesture.GestureId,
            gesture.OperatorGestureId,
            gesture.Tool,
            _residentNativeMeshRevision,
            targetMesh,
            _residentNativeSelectionRevision,
            targetSelection,
            _residentNativeTopologyGeneration);
    }

    private SortedDictionary<int, SortedDictionary<uint, (double X, double Y, double Z)>>
        ResidentNativeGeometryPayload(IReadOnlyList<NativeMeshDirtyRange> ranges)
    {
        var groups = new SortedDictionary<int, SortedDictionary<uint, (double, double, double)>>();
        foreach (var range in ranges)
        {
            if (range.VertexCount == 0)
            {
                continue;
            }
            var read = RequireResidentNativeSession().ReadVertices(
                range.SubmeshIndex,
                range.FirstVertex,
                range.VertexCount);
            RequireResidentNativeSuccess(read.Result, "terminal vertex read");
            if (!groups.TryGetValue(range.SubmeshIndex, out var vertices))
            {
                vertices = new SortedDictionary<uint, (double, double, double)>();
                groups[range.SubmeshIndex] = vertices;
            }
            for (uint offset = 0; offset < read.WrittenVertexCount; offset++)
            {
                var position = checked((int)offset * 3);
                vertices[checked(range.FirstVertex + offset)] = (
                    read.PositionsXyz[position],
                    read.PositionsXyz[position + 1],
                    read.PositionsXyz[position + 2]);
            }
        }
        return groups;
    }

    private byte[] SerializeResidentNativeTransaction(
        ResidentNativeGesture gesture,
        SortedDictionary<int, SortedDictionary<uint, (double X, double Y, double Z)>> geometry,
        IReadOnlyList<NativeMeshSelectionChange> selection,
        ulong targetMeshRevision,
        ulong targetSelectionRevision)
    {
        const uint headerSize = 96;
        var flags = (geometry.Count > 0 ? 1u : 0u) | (selection.Count > 0 ? 2u : 0u);
        var length = checked(
            headerSize
            + geometry.Sum(group => 8u + checked((uint)group.Value.Count * 28u))
            + checked((uint)selection.Count * 24u));
        using var stream = new MemoryStream(checked((int)length));
        using var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true);
        writer.Write(Encoding.ASCII.GetBytes("CDMWMIT1"));
        writer.Write(1u);
        writer.Write(headerSize);
        writer.Write((uint)gesture.Tool);
        writer.Write(flags);
        writer.Write(ResidentSessionKey(_residentNativeSessionId));
        writer.Write(gesture.GestureId);
        writer.Write(_residentNativeMeshRevision);
        writer.Write(targetMeshRevision);
        writer.Write(_residentNativeSelectionRevision);
        writer.Write(targetSelectionRevision);
        writer.Write(_residentNativeTopologyGeneration);
        writer.Write(checked((uint)geometry.Count));
        writer.Write(checked((uint)selection.Count));
        writer.Write((ulong)length);
        foreach (var (submeshIndex, vertices) in geometry)
        {
            writer.Write(submeshIndex);
            writer.Write(checked((uint)vertices.Count));
            foreach (var (vertexIndex, position) in vertices)
            {
                writer.Write(vertexIndex);
                writer.Write(position.X);
                writer.Write(position.Y);
                writer.Write(position.Z);
            }
        }
        foreach (var change in selection)
        {
            writer.Write(change.SubmeshIndex);
            writer.Write((uint)change.Target);
            writer.Write(change.FirstElement);
            writer.Write(change.SecondElement);
            writer.Write(1u);
            writer.Write(change.Selected ? 1u : 0u);
        }
        writer.Flush();
        return stream.ToArray();
    }
}
