"""Read-only typed motion spaces; unsupported engine features remain explicit.

The reflected file's stored triangulation is authoritative. No triangulation is
invented for a non-collinear space that omits it.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from cdmw.core.prefab_binary import decode_prefab_binary


class BlendError(ValueError):
    pass


def numbers(values, name, code='f'):
    value = next((n for n in values if n.name == name), None)
    if value is None:
        return ()
    width = struct.calcsize('<' + code)
    if len(value.raw) % width:
        raise BlendError(f'{name}: invalid typed array length')
    result = struct.unpack('<' + code * (len(value.raw) // width), value.raw)
    if any(not math.isfinite(v) for v in result):
        raise BlendError(f'{name}: non-finite value')
    return result


def scalar(values, name, code='f', default=None):
    result = numbers(values, name, code)
    if len(result) > 1:
        raise BlendError(f'{name}: expected one value')
    return result[0] if result else default


@dataclass(frozen=True)
class Dimension:
    name: str
    minimum: float
    maximum: float
    automatic: bool | None = None
    scale: float | None = None
    smoothing: float | None = None
    parent_parameter: bool | None = None

    @property
    def input_bounds(self):
        scale = self.scale if self.scale is not None else 1.
        return tuple(sorted((self.minimum / scale, self.maximum / scale))) if scale else (0., 0.)


@dataclass(frozen=True)
class Example:
    parameters: tuple[float, ...]
    clips: tuple[int, ...]
    probabilities: tuple[int, ...]
    plane: int | None = None


@dataclass(frozen=True)
class Triangle:
    indices: tuple[int, ...]
    vertices: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Plane:
    coordinate: float
    examples: tuple[int, ...]
    triangles: tuple[Triangle, ...]


@dataclass(frozen=True)
class MotionSpace:
    path: str
    skeleton: str
    clips: tuple[str, ...]
    dimensions: tuple[Dimension, ...]
    examples: tuple[Example, ...]
    triangles: tuple[Triangle, ...]
    phases: tuple[tuple[int, ...], ...]
    loop: bool | None
    scale: float | None
    smoothing: tuple[float | None, float | None]
    limitations: tuple[str, ...] = ()
    planes: tuple[Plane, ...] = ()
    keep_weights: int = 0

    def weights(self, parameters):
        """Example weights, clamped to the stored domain and triangle hull."""
        if len(parameters) != len(self.dimensions) or any(not math.isfinite(x) for x in parameters):
            raise BlendError('Parameter dimensions or values are invalid')
        p = tuple(max(d.minimum, min(d.maximum, x * (d.scale if d.scale is not None else 1.)))
                  for d, x in zip(self.dimensions, parameters))
        if not self.examples:
            raise BlendError('No blendspace examples')
        if len(p) <= 2:
            return planar_weights(self.examples, range(len(self.examples)), self.triangles, p)
        if not self.planes:
            raise BlendError('Three-dimensional plane mapping is Unverified')
        lo = hi = self.planes[0]
        for plane in self.planes:
            hi = plane
            if plane.coordinate >= p[2]:
                break
            lo = plane
        t = (max(0., min(1., (p[2] - lo.coordinate) / (hi.coordinate - lo.coordinate)))
             if hi.coordinate > lo.coordinate else 0.)
        result = {}
        for plane, share in ((lo, 1-t), (hi, t)):
            if share <= 0:
                continue
            for index, weight in planar_weights(self.examples, plane.examples, plane.triangles, p[:2]):
                result[index] = result.get(index, 0.) + weight * share
        return tuple(result.items())

    def contributions(self, parameters):
        """Deterministic inspection of the most probable variant of each example.

        Random variant selection is a runtime feature; it is never disguised as
        simultaneous additive blending of alternatives.
        """
        return self.contributions_for_weights(self.weights(parameters))

    def contributions_for_weights(self, weights):
        result = {}
        for index, weight in weights:
            example = self.examples[index]
            choice = max(range(len(example.clips)), key=lambda i: example.probabilities[i])
            clip = example.clips[choice]
            result[clip] = result.get(clip, 0.) + weight
        active = [(self.clips[i], weight) for i, weight in result.items() if weight > 1e-7]
        total = sum(weight for _, weight in active)
        return tuple((path, weight / total) for path, weight in active)

    def phase_seconds(self, index, phase, duration):
        """Map a common normalized phase onto a clip's stored 30-Hz boundaries.

        Only boundaries proven to end at that clip's declared duration are used.
        A missing or contradictory phase table must not silently pass this check.
        """
        marks = self.phases[index] if index < len(self.phases) else ()
        if len(marks) < 2 or abs(marks[-1] / 30 - duration) > 1 / 30 + 1e-5:
            raise BlendError('Phase timing is Unverified for this clip')
        phase = max(0., min(1., phase)) * (len(marks) - 1)
        lo = min(len(marks) - 2, int(phase))
        t = phase - lo
        return (marks[lo] * (1 - t) + marks[lo + 1] * t) / 30


def barycentric(point, vertices):
    (ax, ay), (bx, by), (cx, cy) = vertices
    det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    # Relative area test: installed planes may have a very small but valid axis.
    # A fixed area epsilon incorrectly rejects those triangles after unit scaling.
    if abs(det) <= 1e-12 * (abs((by-cy)*(ax-cx)) + abs((cx-bx)*(ay-cy))):
        raise BlendError('Degenerate triangle')
    u = ((by - cy) * (point[0] - cx) + (cx - bx) * (point[1] - cy)) / det
    v = ((cy - ay) * (point[0] - cx) + (ax - cx) * (point[1] - cy)) / det
    return u, v, 1 - u - v


def planar_weights(examples, indices, triangles, point):
    points = {i: examples[i].parameters[:len(point)] for i in indices}
    if not points:
        raise BlendError('Empty blend plane')
    for i, p in points.items():
        if p == tuple(point):
            return ((i, 1.),)
    axes = [i for i in range(len(point)) if max(p[i] for p in points.values()) - min(p[i] for p in points.values()) > 1e-6]
    if len(axes) <= 1 and not triangles:
        if not axes:
            return ((next(iter(points)), 1.),)
        axis = axes[0]
        ordered = sorted(points, key=lambda i: points[i][axis])
        x = point[axis]
        if x <= points[ordered[0]][axis]:
            return ((ordered[0], 1.),)
        for a, b in zip(ordered, ordered[1:]):
            lo, hi = points[a][axis], points[b][axis]
            if hi >= x and hi > lo:
                t = (x - lo) / (hi - lo)
                return ((a, 1-t), (b, t))
        return ((ordered[-1], 1.),)
    if not triangles:
        raise BlendError('No validated triangulation for this plane')
    best = None
    for tri in triangles:
        weights = barycentric(point, tri.vertices)
        if min(weights) >= -1e-6:
            weights = tuple(max(0., w) for w in weights)
            total = sum(weights)
            return tuple((i, w/total) for i, w in zip(tri.indices, weights))
        for a, b in ((0, 1), (1, 2), (2, 0)):
            u, v = tri.vertices[a], tri.vertices[b]
            length = sum((v[k] - u[k]) ** 2 for k in range(2))
            if length == 0:
                continue
            t = max(0., min(1., sum((point[k] - u[k]) * (v[k] - u[k]) for k in range(2)) / length))
            distance = sum((point[k] - (u[k] + t * (v[k] - u[k]))) ** 2 for k in range(2))
            if best is None or distance < best[0]:
                best = (distance, ((tri.indices[a], 1-t), (tri.indices[b], t)))
    if best is None:
        raise BlendError('Degenerate triangulation')
    return best[1]


def validated_triangles(triangles, examples, limitations):
    result = []
    for triangle in triangles:
        for index, point in zip(triangle.indices, triangle.vertices):
            if index < 0 or index >= len(examples):
                raise BlendError('Triangle example index outside array')
            if len(examples[index].parameters) < 2 or any(abs(a-b) > 1e-4 for a,b in zip(examples[index].parameters[:2], point)):
                raise BlendError('Triangle vertices disagree with example parameters')
        try:
            barycentric(triangle.vertices[0], triangle.vertices)
        except BlendError:
            limitations.append('Degenerate stored triangles: excluded from interpolation')
            continue
        result.append(triangle)
    return tuple(result)


def decode_planes(doc, examples, triangles, limitations):
    splits = numbers(doc.root_numbers, '_thirdDimensionSplitInfo')
    point_map = numbers(doc.root_numbers, '_delaunayPointIndexMap', 'H')
    collection = [c for c in doc.collections if c.owner_type == 'ParameterizedMotionSpace' and c.member_name == '_delaunayTriangles']
    if len(collection) != 1 or len(splits) != collection[0].count or not splits:
        raise BlendError('Invalid blend plane count')
    if any(a >= b for a,b in zip(splits, splits[1:])) or len(point_map) != len(examples)*len(splits):
        raise BlendError('Invalid blend plane knots or point map')
    objects = [o for o in doc.objects if o.component_type == 'DelaunayTriangle']
    planes, partition = [], []
    for i, (start, end) in enumerate(collection[0].elements):
        block = point_map[i*len(examples):(i+1)*len(examples)]
        # Installed maps have example-count stride and zero-filled trailing slots.
        # The complete partition check below disambiguates example zero from padding.
        members = block[:max([j for j,v in enumerate(block) if v] or [0])+1]
        if members != tuple(sorted(set(members))) or any(v >= len(examples) for v in members):
            raise BlendError('Invalid blend plane example map')
        for v in members:
            if examples[v].plane is not None and examples[v].plane != i:
                raise BlendError('Explicit example plane disagrees with point map')
        partition.extend(members)
        mapped = []
        for obj, tri in zip(objects, triangles):
            if not start < obj.offset < end:
                continue
            if any(j < 0 or j >= len(members) for j in tri.indices):
                raise BlendError('Triangle index outside plane point map')
            mapped.append(Triangle(tuple(members[j] for j in tri.indices), tri.vertices))
        planes.append(Plane(splits[i], members, validated_triangles(mapped, examples, limitations)))
    if sorted(partition) != list(range(len(examples))):
        raise BlendError('Blend plane map is not a complete example partition')
    return tuple(planes)


def decode(data, *, path=''):
    doc = decode_prefab_binary(data)
    if doc.root_type != 'ParameterizedMotionSpace' or not doc.walk_complete:
        raise BlendError(doc.walk_note or 'Not a complete motion space')
    if any(o.type_source != 'stated' for o in doc.objects):
        raise BlendError('Motion space contains inferred object types')
    root = dict((k, v.text) for k, v in doc.root_values)
    clips = tuple(v.text.replace('\\', '/').lower() for k, v in doc.root_values if k == '_animationFileNames')
    clips = tuple(p if p.startswith('character/') else 'character/motion/' + p for p in clips)
    bounds = numbers(doc.root_numbers, '_parameterMinMax')
    dims, examples, triangles, phases, limitations = [], [], [], [], []
    for obj in doc.objects:
        values = obj.numbers
        if obj.component_type == 'ParameterDimension':
            i = len(dims)
            if len(bounds) < 2 * i + 2 or bounds[2*i] > bounds[2*i+1]:
                raise BlendError('Invalid dimension bounds')
            names = dict((k, v.text) for k, v in obj.values)
            dims.append(Dimension(names.get('_dimensionType', f'Parameter {i+1}'), *bounds[2*i:2*i+2],
                                  scalar(values, '_enableParameterCalculation', '?'),
                                  scalar(values, '_parameterScale', default=1.), scalar(values, '_parameterSmoothingFactor', default=0.),
                                  scalar(values, '_useParentParameter', '?')))
        elif obj.component_type == 'ParameterizedMotionExample':
            indices = numbers(values, '_animationDataIndex', 'I')
            probabilities = numbers(values, '_animationDataProbability', 'H')
            if not indices or len(indices) != len(probabilities) or not any(probabilities):
                raise BlendError('Invalid animation alternatives')
            if any(i >= len(clips) for i in indices):
                raise BlendError('Example clip index outside animation array')
            if len(indices) > 1:
                limitations.append('Random alternatives: inspecting the most probable clip')
            examples.append(Example(numbers(values, '_parameters'), indices, probabilities,
                                    scalar(values, '_thirdParameterPlaneIndex', 'i')))
        elif obj.component_type == 'DelaunayTriangle':
            verts = numbers(values, '_vert')
            indices = numbers(values, '_index', 'h')
            if len(verts) != 6 or len(indices) != 3:
                raise BlendError('Invalid triangle arrays')
            triangles.append(Triangle(indices, tuple(zip(verts[::2], verts[1::2]))))
        elif obj.component_type == 'MotionPhaseInfo':
            marks = numbers(values, '_phases', 'H')
            if any(a > b for a, b in zip(marks, marks[1:])):
                raise BlendError('Phase boundaries are not ordered')
            phases.append(marks)
        elif obj.component_type != 'DelaunayTriangulation':
            limitations.append(f'Unsupported feature: {obj.component_type}')
    if not 1 <= len(dims) <= 3 or any(len(e.parameters) != len(dims) for e in examples):
        raise BlendError('Example dimensions disagree with the declared dimensions')
    planes = ()
    if len(dims) <= 2:
        triangles = validated_triangles(triangles, examples, limitations)
    else:
        planes = decode_planes(doc, examples, triangles, limitations)
        triangles = tuple(t for p in planes for t in p.triangles)
    keep = scalar(doc.root_numbers, '_keepInitialBlendWeights', 'i', default=0)
    if keep == 2:
        limitations.append('Previous-motion weights: Unverified; inspecting manually initialized weights')
    elif keep not in (0, 1):
        limitations.append(f'Unsupported initial weight mode: {keep}')
    limitations.append('Automatic parameter calculation: Unverified; manual inputs precede the stored parameter scale')
    return MotionSpace(path, root.get('_skeletonFileName', ''), clips, tuple(dims), tuple(examples),
                       tuple(triangles), tuple(phases), scalar(doc.root_numbers, '_isLoopMotionBlending', '?'),
                       scalar(doc.root_numbers, '_animationScale', default=1.),
                       (scalar(doc.root_numbers, '_weightSmoothingMinSpeed', default=1.75),
                        scalar(doc.root_numbers, '_weightSmoothingMaxSpeed', default=3.5)),
                       tuple(dict.fromkeys(limitations)), planes, keep)
