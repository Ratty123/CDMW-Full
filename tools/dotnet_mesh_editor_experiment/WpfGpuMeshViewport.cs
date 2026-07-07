using System.Runtime.InteropServices;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Media.Media3D;
using System.Windows.Shapes;
using System.Windows.Interop;
using SD = System.Drawing;
using WpfColor = System.Windows.Media.Color;

namespace Cdmw.MeshEditorExperiment;

internal sealed class WpfGpuMeshViewport : IDisposable
{
    private readonly ObjDocument _document;
    private readonly NetMaterialSet _materials;
    private readonly NetTextureSet _textureSet;
    private readonly Viewport3D _viewport = new();
    private readonly Canvas _overlay = new();
    private readonly ModelVisual3D _modelVisual = new();
    private readonly OrthographicCamera _camera = new();

    public WpfGpuMeshViewport(ObjDocument document, NetMaterialSet materials, NetTextureSet textureSet)
    {
        _document = document;
        _materials = materials;
        _textureSet = textureSet;
        Root = new Grid { Background = new SolidColorBrush(WpfColor.FromRgb(23, 25, 29)) };
        _viewport.Camera = _camera;
        _viewport.IsHitTestVisible = false;
        _overlay.IsHitTestVisible = false;
        _overlay.Background = System.Windows.Media.Brushes.Transparent;
        Root.Children.Add(_viewport);
        Root.Children.Add(_overlay);
        System.Windows.Controls.Panel.SetZIndex(_overlay, 10);
        RefreshGeometry();
    }

    public Grid Root { get; }

    public void RefreshGeometry()
    {
        var scene = new Model3DGroup();
        scene.Children.Add(new AmbientLight(WpfColor.FromRgb(92, 100, 112)));
        scene.Children.Add(new DirectionalLight(WpfColor.FromRgb(235, 242, 250), new Vector3D(-0.4, -0.7, -0.6)));
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var model = BuildSubmeshModel(submeshIndex, _document.Submeshes[submeshIndex]);
            if (model is not null)
            {
                scene.Children.Add(model);
            }
        }
        _modelVisual.Content = scene;
        _viewport.Children.Clear();
        _viewport.Children.Add(_modelVisual);
    }

    public void UpdateCamera(
        Vec3 center,
        (Vec3 Min, Vec3 Max) bounds,
        float yaw,
        float pitch,
        float zoom,
        float panX,
        float panY,
        int viewportWidth,
        int viewportHeight)
    {
        var width = Math.Max(1, viewportWidth);
        var height = Math.Max(1, viewportHeight);
        _overlay.Width = width;
        _overlay.Height = height;
        var forward = new Vector3D(
            Math.Sin(yaw) * Math.Cos(pitch),
            Math.Sin(pitch),
            Math.Cos(yaw) * Math.Cos(pitch));
        if (forward.LengthSquared < 0.0001)
        {
            forward = new Vector3D(0, 0, 1);
        }
        forward.Normalize();
        var right = new Vector3D(Math.Cos(yaw), 0.0, -Math.Sin(yaw));
        if (right.LengthSquared < 0.0001)
        {
            right = new Vector3D(1, 0, 0);
        }
        right.Normalize();
        var up = Vector3D.CrossProduct(right, forward);
        if (up.LengthSquared < 0.0001)
        {
            up = new Vector3D(0, 1, 0);
        }
        up.Normalize();
        var size = Math.Max(bounds.Max.X - bounds.Min.X, Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
        var distance = Math.Max(10.0, size * 4.0 + 10.0);
        var panWorld = (-panX / Math.Max(zoom, 0.001f)) * right + (panY / Math.Max(zoom, 0.001f)) * up;
        var target = new Point3D(center.X, center.Y, center.Z) + panWorld;
        _camera.Position = target - (forward * distance);
        _camera.LookDirection = forward * distance;
        _camera.UpDirection = up;
        _camera.Width = Math.Max(0.001, width / Math.Max(zoom, 0.001f));
        _camera.NearPlaneDistance = 0.001;
        _camera.FarPlaneDistance = Math.Max(1000.0, distance * 8.0);
    }

    public void UpdateOverlay(
        NetEdgeTopology edgeTopology,
        IReadOnlySet<int> selectedEdges,
        int hoverEdgeId,
        SD.Rectangle? edgeSelectionRectangle,
        IReadOnlyDictionary<int, HashSet<int>> selectedVertices,
        IReadOnlyDictionary<int, HashSet<int>> selectedFaces,
        IReadOnlySet<int> selectedSources,
        int selectedSubmeshIndex,
        bool showWire,
        bool showXRay,
        Func<Vec3, SD.PointF> project)
    {
        _overlay.Children.Clear();
        if (showWire || showXRay)
        {
            foreach (var edge in edgeTopology.Edges)
            {
                AddEdgeLine(edge, project, WpfColor.FromArgb(showXRay ? (byte)95 : (byte)65, 120, 158, 196), showXRay ? 0.9 : 0.7);
            }
        }
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            if (!selectedFaces.TryGetValue(submeshIndex, out var faces) && !selectedSources.Contains(submeshIndex) && selectedSubmeshIndex != submeshIndex)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            var wholePart = selectedSources.Contains(submeshIndex) || selectedSubmeshIndex == submeshIndex;
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                if (!wholePart && (faces is null || !faces.Contains(faceIndex)))
                {
                    continue;
                }
                AddFacePolygon(submesh, submesh.Faces[faceIndex], project);
            }
        }
        foreach (var edge in edgeTopology.Edges)
        {
            var selected = selectedEdges.Contains(edge.Id);
            var hovered = edge.Id == hoverEdgeId;
            if (selected || hovered)
            {
                AddEdgeLine(edge, project, hovered ? WpfColor.FromArgb(245, 96, 202, 255) : WpfColor.FromArgb(245, 255, 224, 92), hovered ? 2.4 : 2.2);
            }
        }
        if (edgeSelectionRectangle.HasValue)
        {
            AddSelectionRectangle(edgeSelectionRectangle.Value);
        }
        foreach (var pair in selectedVertices)
        {
            if (pair.Key < 0 || pair.Key >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[pair.Key];
            foreach (var vertexIndex in pair.Value)
            {
                if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                {
                    continue;
                }
                var point = project(submesh.Vertices[vertexIndex]);
                AddVertexMarker(point);
            }
        }
    }

    private GeometryModel3D? BuildSubmeshModel(int submeshIndex, ObjSubmesh submesh)
    {
        var geometry = new MeshGeometry3D();
        var normalMap = _textureSet.BitmapForPath(_materials.NormalTexturePathForSubmesh(submeshIndex));
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var start = geometry.Positions.Count;
            var valid = true;
            var faceNormal = FaceNormal(submesh, face);
            var tangentSpace = FaceTangentSpace(submesh, face, faceNormal);
            foreach (var corner in face.Corners)
            {
                if (corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count)
                {
                    valid = false;
                    break;
                }
                var vertex = submesh.Vertices[corner.VertexIndex];
                geometry.Positions.Add(new Point3D(vertex.X, vertex.Y, vertex.Z));
                var baseNormal = NormalForCorner(submesh, corner, faceNormal);
                geometry.Normals.Add(NormalFromMap(submesh, corner, baseNormal, tangentSpace.Tangent, tangentSpace.Bitangent, normalMap));
                if (corner.UvIndex >= 0 && corner.UvIndex < submesh.Uvs.Count)
                {
                    var uv = submesh.Uvs[corner.UvIndex];
                    geometry.TextureCoordinates.Add(new System.Windows.Point(uv.U, 1.0 - uv.V));
                }
                else
                {
                    geometry.TextureCoordinates.Add(new System.Windows.Point(0.0, 0.0));
                }
            }
            if (!valid)
            {
                var remove = geometry.Positions.Count - start;
                for (var index = 0; index < remove; index++)
                {
                    geometry.Positions.RemoveAt(geometry.Positions.Count - 1);
                    geometry.Normals.RemoveAt(geometry.Normals.Count - 1);
                    geometry.TextureCoordinates.RemoveAt(geometry.TextureCoordinates.Count - 1);
                }
                continue;
            }
            geometry.TriangleIndices.Add(start);
            geometry.TriangleIndices.Add(start + 1);
            geometry.TriangleIndices.Add(start + 2);
        }
        if (geometry.Positions.Count == 0)
        {
            return null;
        }
        var material = BuildMaterial(submeshIndex);
        return new GeometryModel3D(geometry, material) { BackMaterial = material };
    }

    private static Vector3D NormalForCorner(ObjSubmesh submesh, ObjCorner corner, Vector3D fallback)
    {
        if (corner.NormalIndex >= 0 && corner.NormalIndex < submesh.Normals.Count)
        {
            var normal = submesh.Normals[corner.NormalIndex];
            var vector = new Vector3D(normal.X, normal.Y, normal.Z);
            if (vector.LengthSquared > 0.0001)
            {
                vector.Normalize();
                return vector;
            }
        }
        return fallback;
    }

    private static Vector3D NormalFromMap(ObjSubmesh submesh, ObjCorner corner, Vector3D baseNormal, Vector3D tangent, Vector3D bitangent, SD.Bitmap? normalMap)
    {
        if (normalMap is null || corner.UvIndex < 0 || corner.UvIndex >= submesh.Uvs.Count)
        {
            return baseNormal;
        }
        var uv = submesh.Uvs[corner.UvIndex];
        var x = Math.Clamp((int)Math.Round(uv.U * (normalMap.Width - 1)), 0, normalMap.Width - 1);
        var y = Math.Clamp((int)Math.Round((1.0f - uv.V) * (normalMap.Height - 1)), 0, normalMap.Height - 1);
        var color = normalMap.GetPixel(x, y);
        var nx = (color.R / 127.5) - 1.0;
        var ny = (color.G / 127.5) - 1.0;
        var nz = (color.B / 127.5) - 1.0;
        var mapped = (tangent * nx) + (bitangent * ny) + (baseNormal * nz);
        if (mapped.LengthSquared < 0.0001)
        {
            return baseNormal;
        }
        mapped.Normalize();
        return mapped;
    }

    private static (Vector3D Tangent, Vector3D Bitangent) FaceTangentSpace(ObjSubmesh submesh, ObjFace face, Vector3D normal)
    {
        if (face.Corners.Length != 3 || face.Corners.Any(corner => corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count || corner.UvIndex < 0 || corner.UvIndex >= submesh.Uvs.Count))
        {
            return FallbackTangentSpace(normal);
        }
        var p0 = submesh.Vertices[face.Corners[0].VertexIndex];
        var p1 = submesh.Vertices[face.Corners[1].VertexIndex];
        var p2 = submesh.Vertices[face.Corners[2].VertexIndex];
        var uv0 = submesh.Uvs[face.Corners[0].UvIndex];
        var uv1 = submesh.Uvs[face.Corners[1].UvIndex];
        var uv2 = submesh.Uvs[face.Corners[2].UvIndex];
        var edge1 = new Vector3D(p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z);
        var edge2 = new Vector3D(p2.X - p0.X, p2.Y - p0.Y, p2.Z - p0.Z);
        var du1 = uv1.U - uv0.U;
        var dv1 = uv1.V - uv0.V;
        var du2 = uv2.U - uv0.U;
        var dv2 = uv2.V - uv0.V;
        var determinant = (du1 * dv2) - (du2 * dv1);
        if (Math.Abs(determinant) < 0.000001)
        {
            return FallbackTangentSpace(normal);
        }
        var scale = 1.0 / determinant;
        var tangent = (edge1 * dv2 - edge2 * dv1) * scale;
        var bitangent = (edge2 * du1 - edge1 * du2) * scale;
        tangent -= normal * Vector3D.DotProduct(normal, tangent);
        if (tangent.LengthSquared < 0.0001)
        {
            return FallbackTangentSpace(normal);
        }
        tangent.Normalize();
        bitangent -= normal * Vector3D.DotProduct(normal, bitangent);
        bitangent -= tangent * Vector3D.DotProduct(tangent, bitangent);
        if (bitangent.LengthSquared < 0.0001)
        {
            bitangent = Vector3D.CrossProduct(normal, tangent);
        }
        bitangent.Normalize();
        return (tangent, bitangent);
    }

    private static (Vector3D Tangent, Vector3D Bitangent) FallbackTangentSpace(Vector3D normal)
    {
        var tangent = Vector3D.CrossProduct(normal, Math.Abs(normal.Y) < 0.95 ? new Vector3D(0, 1, 0) : new Vector3D(1, 0, 0));
        if (tangent.LengthSquared < 0.0001)
        {
            tangent = new Vector3D(1, 0, 0);
        }
        tangent.Normalize();
        var bitangent = Vector3D.CrossProduct(normal, tangent);
        bitangent.Normalize();
        return (tangent, bitangent);
    }

    private static Vector3D FaceNormal(ObjSubmesh submesh, ObjFace face)
    {
        if (face.Corners.Length != 3)
        {
            return new Vector3D(0, 1, 0);
        }
        var vertexA = face.Corners[0].VertexIndex;
        var vertexB = face.Corners[1].VertexIndex;
        var vertexC = face.Corners[2].VertexIndex;
        if (vertexA < 0 || vertexB < 0 || vertexC < 0 || vertexA >= submesh.Vertices.Count || vertexB >= submesh.Vertices.Count || vertexC >= submesh.Vertices.Count)
        {
            return new Vector3D(0, 1, 0);
        }
        var a = submesh.Vertices[vertexA];
        var b = submesh.Vertices[vertexB];
        var c = submesh.Vertices[vertexC];
        var ab = new Vector3D(b.X - a.X, b.Y - a.Y, b.Z - a.Z);
        var ac = new Vector3D(c.X - a.X, c.Y - a.Y, c.Z - a.Z);
        var normal = Vector3D.CrossProduct(ab, ac);
        if (normal.LengthSquared < 0.0001)
        {
            return new Vector3D(0, 1, 0);
        }
        normal.Normalize();
        return normal;
    }

    private Material BuildMaterial(int submeshIndex)
    {
        var group = new MaterialGroup();
        var baseBrush = TextureBrushForPath(_materials.BaseTexturePathForSubmesh(submeshIndex));
        group.Children.Add(baseBrush is not null
            ? new DiffuseMaterial(baseBrush)
            : new DiffuseMaterial(new SolidColorBrush(FallbackColor(submeshIndex))));
        group.Children.Add(new SpecularMaterial(SpecularBrushForSubmesh(submeshIndex), SpecularPowerForSubmesh(submeshIndex)));
        var emissiveBrush = TextureBrushForPath(_materials.EmissiveTexturePathForSubmesh(submeshIndex));
        if (emissiveBrush is not null)
        {
            group.Children.Add(new EmissiveMaterial(emissiveBrush));
        }
        return group;
    }

    private SolidColorBrush SpecularBrushForSubmesh(int submeshIndex)
    {
        var specular = _textureSet.AverageColorForPath(_materials.SpecularTexturePathForSubmesh(submeshIndex));
        var metallic = _textureSet.AverageColorForPath(_materials.MetallicTexturePathForSubmesh(submeshIndex));
        var chosen = specular ?? metallic;
        if (chosen is null)
        {
            return new SolidColorBrush(WpfColor.FromRgb(210, 220, 230));
        }
        var color = chosen.Value;
        var brush = new SolidColorBrush(WpfColor.FromArgb(color.A, color.R, color.G, color.B));
        brush.Freeze();
        return brush;
    }

    private double SpecularPowerForSubmesh(int submeshIndex)
    {
        var roughness = _textureSet.AverageBrightnessForPath(_materials.RoughnessTexturePathForSubmesh(submeshIndex));
        var height = _textureSet.AverageBrightnessForPath(_materials.HeightTexturePathForSubmesh(submeshIndex));
        return Math.Clamp(96.0 - (roughness * 72.0) + (height * 8.0), 8.0, 128.0);
    }

    private ImageBrush? TextureBrushForPath(string texturePath)
    {
        var bitmap = _textureSet.BitmapForPath(texturePath);
        if (bitmap is null)
        {
            return null;
        }
        try
        {
            var image = BitmapSourceFromBitmap(bitmap);
            image.Freeze();
            var brush = new ImageBrush(image) { Stretch = Stretch.Fill };
            brush.Freeze();
            return brush;
        }
        catch
        {
            return null;
        }
    }

    private static BitmapSource BitmapSourceFromBitmap(SD.Bitmap bitmap)
    {
        var handle = bitmap.GetHbitmap();
        try
        {
            return Imaging.CreateBitmapSourceFromHBitmap(handle, IntPtr.Zero, System.Windows.Int32Rect.Empty, BitmapSizeOptions.FromEmptyOptions());
        }
        finally
        {
            DeleteObject(handle);
        }
    }

    [DllImport("gdi32.dll")]
    private static extern bool DeleteObject(IntPtr hObject);

    private void AddEdgeLine(NetEdge edge, Func<Vec3, SD.PointF> project, WpfColor color, double thickness)
    {
        if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
        {
            return;
        }
        var submesh = _document.Submeshes[edge.SubmeshIndex];
        if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
        {
            return;
        }
        var a = project(submesh.Vertices[edge.VertexA]);
        var b = project(submesh.Vertices[edge.VertexB]);
        _overlay.Children.Add(new Line
        {
            X1 = a.X,
            Y1 = a.Y,
            X2 = b.X,
            Y2 = b.Y,
            Stroke = new SolidColorBrush(color),
            StrokeThickness = thickness,
            IsHitTestVisible = false,
        });
    }

    private void AddFacePolygon(ObjSubmesh submesh, ObjFace face, Func<Vec3, SD.PointF> project)
    {
        if (face.Corners.Length != 3)
        {
            return;
        }
        var polygon = new Polygon
        {
            Fill = new SolidColorBrush(WpfColor.FromArgb(68, 255, 224, 92)),
            Stroke = new SolidColorBrush(WpfColor.FromArgb(180, 255, 224, 92)),
            StrokeThickness = 1.0,
            IsHitTestVisible = false,
        };
        foreach (var corner in face.Corners)
        {
            if (corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count)
            {
                return;
            }
            var point = project(submesh.Vertices[corner.VertexIndex]);
            polygon.Points.Add(new System.Windows.Point(point.X, point.Y));
        }
        _overlay.Children.Add(polygon);
    }

    private void AddSelectionRectangle(SD.Rectangle rectangle)
    {
        var shape = new System.Windows.Shapes.Rectangle
        {
            Width = Math.Max(1, rectangle.Width),
            Height = Math.Max(1, rectangle.Height),
            Fill = new SolidColorBrush(WpfColor.FromArgb(34, 96, 202, 255)),
            Stroke = new SolidColorBrush(WpfColor.FromArgb(190, 96, 202, 255)),
            StrokeThickness = 1.0,
            StrokeDashArray = new DoubleCollection { 3.0, 2.0 },
            IsHitTestVisible = false,
        };
        Canvas.SetLeft(shape, rectangle.Left);
        Canvas.SetTop(shape, rectangle.Top);
        _overlay.Children.Add(shape);
    }

    private void AddVertexMarker(SD.PointF point)
    {
        var ellipse = new Ellipse
        {
            Width = 7,
            Height = 7,
            Fill = new SolidColorBrush(WpfColor.FromRgb(255, 224, 92)),
            Stroke = new SolidColorBrush(WpfColor.FromRgb(44, 25, 10)),
            StrokeThickness = 1.0,
            IsHitTestVisible = false,
        };
        Canvas.SetLeft(ellipse, point.X - 3.5);
        Canvas.SetTop(ellipse, point.Y - 3.5);
        _overlay.Children.Add(ellipse);
    }

    private static WpfColor FallbackColor(int index)
    {
        var palette = new[]
        {
            WpfColor.FromRgb(79, 112, 152),
            WpfColor.FromRgb(104, 132, 92),
            WpfColor.FromRgb(132, 98, 84),
            WpfColor.FromRgb(118, 98, 150),
        };
        return palette[Math.Abs(index) % palette.Length];
    }

    public void Dispose()
    {
        _overlay.Children.Clear();
        _viewport.Children.Clear();
    }
}
