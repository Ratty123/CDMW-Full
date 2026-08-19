using System.IO;
using System.Numerics;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// One emitter of an effect as the host described it in effect_preview.json
/// (schema 1): what the CPU simulation needs and nothing the game's GPU
/// simulation would add. Curves are sampled evenly over the particle's life.
/// </summary>
internal sealed class EffectEmitterPreview
{
    public string Name = string.Empty;
    public string Kind = "billboard";
    public string TexturePath = string.Empty;
    public string Blend = "additive";
    public int Burst = 1;
    public float BurstsPerSecond = 10.0f;
    public int MaxParticles = 200;
    public float LifeMin = 0.5f;
    public float LifeMax = 1.0f;
    public bool Loop = true;
    public float SpawnTime;
    public string Spawn = "spread";
    public Vector3 Spread = new(0.25f, 0.25f, 0.25f);
    public Vector3[] Points = Array.Empty<Vector3>();
    public Vector3 ForceMin;
    public Vector3 ForceMax;
    public float Damping;
    public float SpeedLimit;
    public Vector3 ScaleMin = Vector3.One;
    public Vector3 ScaleMax = Vector3.One;
    public float RotationMin;
    public float RotationMax;
    public float[] ScaleOverLife = Array.Empty<float>();
    public float[] AlphaOverLife = Array.Empty<float>();
    public Vector3[] ColorOverLife = Array.Empty<Vector3>();
    public Vector3 EmissiveColor = Vector3.One;
    public float Brightness = 1.0f;
    public float BeamWidth;
    public float BeamJitter;
    public float BeamLength;
    public Vector3 BeamAxis;
    public float Mass = 1.0f;
    public float SimulationSpeed = 1.0f;
    public int SequenceX = 1;
    public int SequenceY = 1;
    public float VelocityStretch;

    /// <summary>The colour curve's peak, so a dim HDR fire still shows: colours are drawn over this.</summary>
    public float ColorPeak = 1.0f;

    public bool IsAdditive => !string.Equals(Blend, "alpha", StringComparison.OrdinalIgnoreCase);
    public bool IsBeam => string.Equals(Kind, "beam", StringComparison.OrdinalIgnoreCase);
}

/// <summary>The effect's description read from a package: emitters, box, notes.</summary>
internal sealed class EffectParticlePreview
{
    public const string FileName = "effect_preview.json";

    public string Stem = string.Empty;
    public Vector3 BoxMin = new(-0.5f, -0.5f, -0.5f);
    public Vector3 BoxMax = new(0.5f, 0.5f, 0.5f);
    public List<string> Notes = new();
    public List<EffectEmitterPreview> Emitters = new();
    public string SourcePath = string.Empty;

    public static EffectParticlePreview? Load(string? packageDirectory)
    {
        if (string.IsNullOrWhiteSpace(packageDirectory))
        {
            return null;
        }
        var path = Path.Combine(packageDirectory, FileName);
        if (!File.Exists(path))
        {
            return null;
        }
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object || Int(root, "schema", 0) != 1)
        {
            return null;
        }
        var preview = new EffectParticlePreview
        {
            Stem = Text(root, "stem"),
            BoxMin = Vec3(root, "box_min", new Vector3(-0.5f)),
            BoxMax = Vec3(root, "box_max", new Vector3(0.5f)),
            SourcePath = path,
        };
        if (root.TryGetProperty("notes", out var notes) && notes.ValueKind == JsonValueKind.Array)
        {
            foreach (var note in notes.EnumerateArray())
            {
                if (note.ValueKind == JsonValueKind.String)
                {
                    preview.Notes.Add(note.GetString() ?? string.Empty);
                }
            }
        }
        var textureFiles = new Dictionary<string, string>(StringComparer.Ordinal);
        if (root.TryGetProperty("texture_files", out var files) && files.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in files.EnumerateObject())
            {
                if (property.Value.ValueKind == JsonValueKind.String)
                {
                    textureFiles[property.Name] = property.Value.GetString() ?? string.Empty;
                }
            }
        }
        if (root.TryGetProperty("emitters", out var emitters) && emitters.ValueKind == JsonValueKind.Array)
        {
            foreach (var element in emitters.EnumerateArray())
            {
                if (element.ValueKind == JsonValueKind.Object)
                {
                    preview.Emitters.Add(ReadEmitter(element, packageDirectory, textureFiles));
                }
            }
        }
        return preview;
    }

    private static EffectEmitterPreview ReadEmitter(JsonElement element, string packageDirectory, IReadOnlyDictionary<string, string> textureFiles)
    {
        var emitter = new EffectEmitterPreview
        {
            Name = Text(element, "name"),
            Kind = Text(element, "kind", "billboard"),
            Blend = Text(element, "blend", "additive"),
            Burst = Math.Max(1, Int(element, "burst", 1)),
            BurstsPerSecond = Math.Clamp(Float(element, "bursts_per_second", 10.0f), 0.05f, 240.0f),
            MaxParticles = Math.Clamp(Int(element, "max_particles", 200), 1, 4000),
            Loop = Bool(element, "loop", true),
            SpawnTime = Math.Max(0.0f, Float(element, "spawn_time", 0.0f)),
            Spawn = Text(element, "spawn", "spread"),
            Spread = Vec3(element, "spread", new Vector3(0.25f)),
            Damping = Math.Max(0.0f, Float(element, "damping", 0.0f)),
            SpeedLimit = Math.Max(0.0f, Float(element, "speed_limit", 0.0f)),
            EmissiveColor = Vec3(element, "emissive_color", Vector3.One),
            Brightness = Math.Max(0.0f, Float(element, "brightness", 1.0f)),
            BeamWidth = Math.Max(0.0f, Float(element, "beam_width", 0.0f)),
            BeamJitter = Math.Max(0.0f, Float(element, "beam_jitter", 0.0f)),
            BeamLength = Math.Max(0.0f, Float(element, "beam_length", 0.0f)),
            BeamAxis = Vec3(element, "beam_axis", Vector3.Zero),
            Mass = Math.Max(0.0f, Float(element, "mass", 1.0f)),
            SimulationSpeed = Math.Clamp(Float(element, "simulation_speed", 1.0f), 0.05f, 8.0f),
            VelocityStretch = Math.Max(0.0f, Float(element, "velocity_stretch", 0.0f)),
        };
        var life = Floats(element, "life");
        if (life.Length >= 2)
        {
            emitter.LifeMin = Math.Max(0.05f, life[0]);
            emitter.LifeMax = Math.Max(emitter.LifeMin, life[1]);
        }
        var force = Vec3Pair(element, "force");
        emitter.ForceMin = force.Item1;
        emitter.ForceMax = force.Item2;
        var scale = Vec3Pair(element, "scale", Vector3.One);
        emitter.ScaleMin = scale.Item1;
        emitter.ScaleMax = scale.Item2;
        var rotation = Floats(element, "rotation");
        if (rotation.Length >= 2)
        {
            emitter.RotationMin = rotation[0];
            emitter.RotationMax = rotation[1];
        }
        emitter.ScaleOverLife = Floats(element, "scale_over_life");
        emitter.AlphaOverLife = Floats(element, "alpha_over_life");
        emitter.ColorOverLife = Vec3List(element, "color_over_life");
        emitter.Points = Vec3List(element, "points");
        var sequence = Floats(element, "sequence");
        if (sequence.Length >= 2)
        {
            emitter.SequenceX = Math.Clamp((int)MathF.Round(sequence[0]), 1, 16);
            emitter.SequenceY = Math.Clamp((int)MathF.Round(sequence[1]), 1, 16);
        }
        var texture = Text(element, "texture");
        if (!string.IsNullOrWhiteSpace(texture) && textureFiles.TryGetValue(texture, out var relative) && !string.IsNullOrWhiteSpace(relative))
        {
            var candidate = Path.GetFullPath(Path.Combine(packageDirectory, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (File.Exists(candidate))
            {
                emitter.TexturePath = candidate;
            }
        }
        var peak = 0.0f;
        foreach (var colour in emitter.ColorOverLife)
        {
            peak = MathF.Max(peak, MathF.Max(colour.X, MathF.Max(colour.Y, colour.Z)));
        }
        if (peak <= 1e-4f)
        {
            peak = MathF.Max(emitter.EmissiveColor.X, MathF.Max(emitter.EmissiveColor.Y, emitter.EmissiveColor.Z));
        }
        emitter.ColorPeak = peak > 1e-4f ? peak : 1.0f;
        // An emitter whose colour curve and emissive colour are both black multiplies its
        // sprite to nothing, which for an additive blend is an emitter that draws
        // absolutely nothing. That happens when the emitter's own file was not read and
        // only the effect's overrides describe it (the reader says so in its notes), and
        // "the preview shows nothing" is a worse answer than "the preview shows the
        // sprite as it is", so the texture is drawn on its own colours.
        if (peak <= 1e-4f)
        {
            emitter.ColorOverLife = Array.Empty<Vector3>();
            emitter.EmissiveColor = Vector3.One;
            emitter.ColorPeak = 1.0f;
        }
        return emitter;
    }

    private static string Text(JsonElement element, string name, string fallback = "") =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? fallback : fallback;

    private static int Int(JsonElement element, string name, int fallback) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var result) ? result : fallback;

    private static float Float(JsonElement element, string name, float fallback)
    {
        if (element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var result) && double.IsFinite(result))
        {
            return (float)result;
        }
        return fallback;
    }

    private static bool Bool(JsonElement element, string name, bool fallback) =>
        element.TryGetProperty(name, out var value) && (value.ValueKind == JsonValueKind.True || value.ValueKind == JsonValueKind.False) ? value.GetBoolean() : fallback;

    private static float[] Floats(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<float>();
        }
        var list = new List<float>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetDouble(out var number) && double.IsFinite(number))
            {
                list.Add((float)number);
            }
        }
        return list.ToArray();
    }

    private static Vector3 Vec3(JsonElement element, string name, Vector3 fallback)
    {
        var values = Floats(element, name);
        return values.Length >= 3 ? new Vector3(values[0], values[1], values[2]) : fallback;
    }

    private static Vector3[] Vec3List(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<Vector3>();
        }
        var list = new List<Vector3>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Array)
            {
                continue;
            }
            var parts = new List<float>();
            foreach (var part in item.EnumerateArray())
            {
                if (part.ValueKind == JsonValueKind.Number && part.TryGetDouble(out var number) && double.IsFinite(number))
                {
                    parts.Add((float)number);
                }
            }
            if (parts.Count >= 3)
            {
                list.Add(new Vector3(parts[0], parts[1], parts[2]));
            }
        }
        return list.ToArray();
    }

    private static (Vector3, Vector3) Vec3Pair(JsonElement element, string name, Vector3? fallback = null)
    {
        var pair = Vec3List(element, name);
        var basis = fallback ?? Vector3.Zero;
        return pair.Length >= 2 ? (pair[0], pair[1]) : (basis, basis);
    }
}

/// <summary>A live particle of one emitter, in the effect's own frame (metres).</summary>
internal struct EffectParticle
{
    public Vector3 Position;
    public Vector3 Velocity;
    public Vector3 Acceleration;
    public float Age;
    public float Life;
    public float Size;
    public float Rotation;
    public float Seed;
}

/// <summary>A sprite corner the renderer uploads: world position, colour, sprite UV.</summary>
internal readonly record struct EffectParticleVertex(Vector3 Position, Vector4 Color, Vector2 TexCoord);

/// <summary>
/// The CPU simulation of one emitter: bursts by rate while the emitter spawns
/// (always for a looping one; for `spawn_time` then a pause for a one-shot, so it
/// replays), particles pushed by their force over mass, damped, capped, aged, and
/// laid out as camera-facing quads (or a jittered ribbon for a beam) with the
/// curves sampled at their age.
/// </summary>
internal sealed class EffectEmitterSimulation
{
    private const float ReplayPause = 0.6f;
    private const int BeamSegments = 14;
    private const float BeamRerollSeconds = 0.06f;
    private readonly List<EffectParticle> _particles = new();
    private readonly Random _random;
    private float _spawnAccumulator;
    private float _clock;
    private float _beamClock;
    private Vector3[] _beamOffsets = Array.Empty<Vector3>();

    public EffectEmitterSimulation(EffectEmitterPreview emitter, int seed)
    {
        Emitter = emitter;
        _random = new Random(seed);
    }

    public EffectEmitterPreview Emitter { get; }
    public int ParticleCount => _particles.Count;

    public void Reset()
    {
        _particles.Clear();
        _spawnAccumulator = 0.0f;
        _clock = 0.0f;
        _beamClock = 0.0f;
    }

    public void Step(float deltaSeconds)
    {
        var e = Emitter;
        var dt = Math.Clamp(deltaSeconds, 0.0f, 0.1f) * e.SimulationSpeed;
        if (dt <= 0.0f)
        {
            return;
        }
        var previousClock = _clock;
        _clock += dt;
        var spawning = true;
        var windowOpened = previousClock <= 0.0f;
        if (!e.Loop)
        {
            var window = e.SpawnTime > 0.0f ? e.SpawnTime : 0.25f;
            var period = window + e.LifeMax + ReplayPause;
            var phase = _clock % period;
            spawning = phase < window;
            // A short window and a modest rate never meet: a tenth of a second at ten
            // bursts a second reaches an accumulator of 0.99 by the last frame inside the
            // window and spawns nothing, every period, for ever. A burst emitter bursts
            // when its window opens, so the window opening fires one.
            windowOpened = windowOpened || (spawning && previousClock % period >= window);
        }
        if (spawning)
        {
            if (windowOpened)
            {
                _spawnAccumulator = MathF.Max(_spawnAccumulator, 1.0f);
            }
            _spawnAccumulator += e.BurstsPerSecond * dt;
            var bursts = 0;
            while (_spawnAccumulator >= 1.0f && bursts < 8)
            {
                _spawnAccumulator -= 1.0f;
                bursts++;
                for (var index = 0; index < e.Burst && _particles.Count < e.MaxParticles; index++)
                {
                    _particles.Add(SpawnOne());
                }
            }
            if (_spawnAccumulator > 8.0f)
            {
                _spawnAccumulator = 0.0f;
            }
        }
        var dampingFactor = e.Damping > 0.0f ? MathF.Exp(-e.Damping * dt) : 1.0f;
        for (var index = _particles.Count - 1; index >= 0; index--)
        {
            var particle = _particles[index];
            particle.Age += dt;
            if (particle.Age >= particle.Life)
            {
                _particles[index] = _particles[^1];
                _particles.RemoveAt(_particles.Count - 1);
                continue;
            }
            particle.Velocity += particle.Acceleration * dt;
            particle.Velocity *= dampingFactor;
            if (e.SpeedLimit > 0.0f)
            {
                var speed = particle.Velocity.Length();
                if (speed > e.SpeedLimit)
                {
                    particle.Velocity *= e.SpeedLimit / speed;
                }
            }
            particle.Position += particle.Velocity * dt;
            _particles[index] = particle;
        }
        _beamClock += dt;
    }

    private EffectParticle SpawnOne()
    {
        var e = Emitter;
        Vector3 position;
        if (string.Equals(e.Spawn, "points", StringComparison.OrdinalIgnoreCase) && e.Points.Length > 0)
        {
            position = e.Points[_random.Next(e.Points.Length)];
        }
        else
        {
            position = new Vector3(
                Signed() * e.Spread.X,
                Signed() * e.Spread.Y,
                Signed() * e.Spread.Z);
        }
        var force = Vector3.Lerp(e.ForceMin, e.ForceMax, Unit());
        // A reading, not the game's integrator: the force over the particle's mass is its
        // acceleration, and a mass under a twentieth of a kilogram is treated as that so a
        // 0.011 kg ember does not leave the frame in a frame.
        var mass = MathF.Max(0.05f, e.Mass);
        var scale = Vector3.Lerp(e.ScaleMin, e.ScaleMax, Unit());
        return new EffectParticle
        {
            Position = position,
            Velocity = Vector3.Zero,
            Acceleration = force / mass,
            Age = 0.0f,
            Life = e.LifeMin + (e.LifeMax - e.LifeMin) * Unit(),
            Size = MathF.Max(0.001f, (scale.X + scale.Y + scale.Z) / 3.0f),
            Rotation = (e.RotationMin + (e.RotationMax - e.RotationMin) * Unit()) * MathF.PI / 180.0f,
            Seed = Unit(),
        };
    }

    private float Unit() => (float)_random.NextDouble();
    private float Signed() => (float)(_random.NextDouble() * 2.0 - 1.0);

    private static float Sample(float[] curve, float t, float fallback)
    {
        if (curve.Length == 0)
        {
            return fallback;
        }
        if (curve.Length == 1)
        {
            return curve[0];
        }
        var position = Math.Clamp(t, 0.0f, 1.0f) * (curve.Length - 1);
        var low = (int)MathF.Floor(position);
        var high = Math.Min(curve.Length - 1, low + 1);
        var mix = position - low;
        return curve[low] + (curve[high] - curve[low]) * mix;
    }

    private static Vector3 Sample(Vector3[] curve, float t, Vector3 fallback)
    {
        if (curve.Length == 0)
        {
            return fallback;
        }
        if (curve.Length == 1)
        {
            return curve[0];
        }
        var position = Math.Clamp(t, 0.0f, 1.0f) * (curve.Length - 1);
        var low = (int)MathF.Floor(position);
        var high = Math.Min(curve.Length - 1, low + 1);
        return Vector3.Lerp(curve[low], curve[high], position - low);
    }

    /// <summary>
    /// The emitter's sprites as world-space quads: the effect frame is placed by
    /// `model` (the box's placement), sizes scale with it, quads face the camera
    /// through `right`/`up`. Returns the vertex count appended (a multiple of 6).
    /// </summary>
    public int AppendVertices(List<EffectParticleVertex> output, Matrix4x4 model, Vector3 right, Vector3 up, float modelScale)
    {
        var e = Emitter;
        var appended = 0;
        var invPeak = 1.0f / e.ColorPeak;
        var frames = Math.Max(1, e.SequenceX * e.SequenceY);
        var frameWidth = 1.0f / e.SequenceX;
        var frameHeight = 1.0f / e.SequenceY;
        if (e.IsBeam)
        {
            return AppendBeamVertices(output, model, right, up, modelScale, invPeak);
        }
        foreach (var particle in _particles)
        {
            var t = particle.Life > 0.0f ? particle.Age / particle.Life : 1.0f;
            var alpha = Math.Clamp(Sample(e.AlphaOverLife, t, 1.0f), 0.0f, 1.0f);
            if (alpha <= 0.002f)
            {
                continue;
            }
            var size = particle.Size * MathF.Max(0.0f, Sample(e.ScaleOverLife, t, 1.0f)) * modelScale;
            if (size <= 1e-5f)
            {
                continue;
            }
            var colour = Sample(e.ColorOverLife, t, e.EmissiveColor) * invPeak;
            var rgba = new Vector4(
                Math.Clamp(colour.X, 0.0f, 1.0f),
                Math.Clamp(colour.Y, 0.0f, 1.0f),
                Math.Clamp(colour.Z, 0.0f, 1.0f),
                alpha * (e.IsAdditive ? 0.85f : 1.0f));
            var centre = Vector3.Transform(particle.Position, model);
            var cos = MathF.Cos(particle.Rotation);
            var sin = MathF.Sin(particle.Rotation);
            var axisX = (right * cos + up * sin) * (size * 0.5f);
            var axisY = (up * cos - right * sin) * (size * 0.5f);
            if (e.VelocityStretch > 0.0f && particle.Velocity.LengthSquared() > 1e-6f)
            {
                var direction = Vector3.Normalize(Vector3.TransformNormal(particle.Velocity, model));
                var along = direction - Vector3.Dot(direction, Vector3.Normalize(Vector3.Cross(right, up))) * Vector3.Normalize(Vector3.Cross(right, up));
                if (along.LengthSquared() > 1e-6f)
                {
                    along = Vector3.Normalize(along);
                    var across = Vector3.Normalize(Vector3.Cross(along, Vector3.Cross(right, up)));
                    var stretch = 1.0f + MathF.Min(2.0f, e.VelocityStretch * particle.Velocity.Length() * 0.5f);
                    axisY = along * (size * 0.5f * stretch);
                    axisX = across * (size * 0.5f);
                }
            }
            var frame = Math.Min(frames - 1, (int)MathF.Floor(t * frames));
            var u0 = (frame % e.SequenceX) * frameWidth;
            var v0 = (frame / e.SequenceX) * frameHeight;
            var u1 = u0 + frameWidth;
            var v1 = v0 + frameHeight;
            var a = centre - axisX - axisY;
            var b = centre + axisX - axisY;
            var c = centre + axisX + axisY;
            var d = centre - axisX + axisY;
            output.Add(new EffectParticleVertex(a, rgba, new Vector2(u0, v1)));
            output.Add(new EffectParticleVertex(b, rgba, new Vector2(u1, v1)));
            output.Add(new EffectParticleVertex(c, rgba, new Vector2(u1, v0)));
            output.Add(new EffectParticleVertex(a, rgba, new Vector2(u0, v1)));
            output.Add(new EffectParticleVertex(c, rgba, new Vector2(u1, v0)));
            output.Add(new EffectParticleVertex(d, rgba, new Vector2(u0, v0)));
            appended += 6;
        }
        return appended;
    }

    private static int AppendRibbonSegment(List<EffectParticleVertex> output, Vector3 from, Vector3 to, Vector3 halfAcross, Vector4 rgba)
    {
        var a = from - halfAcross;
        var b = from + halfAcross;
        var c = to + halfAcross;
        var d = to - halfAcross;
        output.Add(new EffectParticleVertex(a, rgba, new Vector2(0.0f, 1.0f)));
        output.Add(new EffectParticleVertex(b, rgba, new Vector2(1.0f, 1.0f)));
        output.Add(new EffectParticleVertex(c, rgba, new Vector2(1.0f, 0.0f)));
        output.Add(new EffectParticleVertex(a, rgba, new Vector2(0.0f, 1.0f)));
        output.Add(new EffectParticleVertex(c, rgba, new Vector2(1.0f, 0.0f)));
        output.Add(new EffectParticleVertex(d, rgba, new Vector2(0.0f, 0.0f)));
        return 6;
    }

    private int AppendBeamVertices(List<EffectParticleVertex> output, Matrix4x4 model, Vector3 right, Vector3 up, float modelScale, float invPeak)
    {
        var e = Emitter;
        var appended = 0;
        if (_beamOffsets.Length != BeamSegments + 1 || _beamClock >= BeamRerollSeconds)
        {
            _beamClock = 0.0f;
            _beamOffsets = new Vector3[BeamSegments + 1];
            for (var index = 1; index < BeamSegments; index++)
            {
                _beamOffsets[index] = new Vector3(Signed(), Signed(), Signed());
            }
        }
        var normal = Vector3.Normalize(Vector3.Cross(right, up));
        foreach (var particle in _particles)
        {
            var t = particle.Life > 0.0f ? particle.Age / particle.Life : 1.0f;
            var alpha = Math.Clamp(Sample(e.AlphaOverLife, t, 1.0f), 0.0f, 1.0f);
            if (alpha <= 0.002f)
            {
                continue;
            }
            var colour = Sample(e.ColorOverLife, t, e.EmissiveColor) * invPeak;
            var rgba = new Vector4(Math.Clamp(colour.X, 0.0f, 1.0f), Math.Clamp(colour.Y, 0.0f, 1.0f), Math.Clamp(colour.Z, 0.0f, 1.0f), alpha);
            // the beam runs from the spawn point along the particle's push (its force), a
            // scale's length; without a push, straight up
            var direction = e.BeamAxis.LengthSquared() > 1e-6f
                ? Vector3.Normalize(e.BeamAxis)
                : particle.Acceleration.LengthSquared() > 1e-6f ? Vector3.Normalize(particle.Acceleration) : Vector3.UnitY;
            var length = MathF.Max(0.05f, e.BeamLength > 0.0f ? e.BeamLength : particle.Size * 2.0f);
            var jitter = e.BeamJitter > 0.0f ? e.BeamJitter * length : 0.1f * length;
            var width = MathF.Max(0.003f, e.BeamWidth > 0.0f ? e.BeamWidth : particle.Size * 0.08f) * modelScale;
            var previous = Vector3.Transform(particle.Position, model);
            for (var index = 1; index <= BeamSegments; index++)
            {
                var along = index / (float)BeamSegments;
                var envelope = MathF.Sin(along * MathF.PI);
                var local = particle.Position + direction * (length * along) + _beamOffsets[index] * (jitter * envelope * (0.5f + particle.Seed));
                var point = Vector3.Transform(local, model);
                var segment = point - previous;
                if (segment.LengthSquared() < 1e-10f)
                {
                    continue;
                }
                var across = Vector3.Cross(Vector3.Normalize(segment), normal);
                if (across.LengthSquared() < 1e-8f)
                {
                    across = right;
                }
                across = Vector3.Normalize(across);
                // a bright core and a soft halo three times as wide: the bolt's glow, so a
                // centimetre-wide arc still reads at a distance
                appended += AppendRibbonSegment(output, previous, point, across * (width * 1.5f), rgba with { W = rgba.W * 0.3f });
                appended += AppendRibbonSegment(output, previous, point, across * (width * 0.5f), rgba);
                previous = point;
            }
        }
        return appended;
    }
}
