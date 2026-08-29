using System.Collections;
using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Incremental screen-path simplification with a fixed memory ceiling.
/// First and newest points are exact; turns, spatial deviation, and slow motion
/// keep intermediate samples until the least important interior point must go.
/// </summary>
internal sealed class StrokeSampleBuffer : IReadOnlyList<Point>
{
    internal const int DefaultMaxSamples = 256;
    internal const double DefaultMinSpacingPixels = 2.5;
    internal const long DefaultMaxIntervalMilliseconds = 50;
    internal const double DefaultCurvatureDegrees = 12.0;

    private readonly int _maxSamples;
    private readonly double _minSpacingPixels;
    private readonly long _maxIntervalMilliseconds;
    private readonly double _curvatureDegrees;
    private readonly List<TimedPoint> _samples = new();

    internal StrokeSampleBuffer(
        int maxSamples = DefaultMaxSamples,
        double minSpacingPixels = DefaultMinSpacingPixels,
        long maxIntervalMilliseconds = DefaultMaxIntervalMilliseconds,
        double curvatureDegrees = DefaultCurvatureDegrees)
    {
        if (maxSamples < 2)
        {
            throw new ArgumentOutOfRangeException(nameof(maxSamples));
        }
        if (!double.IsFinite(minSpacingPixels) || minSpacingPixels <= 0.0)
        {
            throw new ArgumentOutOfRangeException(nameof(minSpacingPixels));
        }
        if (maxIntervalMilliseconds <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxIntervalMilliseconds));
        }
        if (!double.IsFinite(curvatureDegrees) || curvatureDegrees <= 0.0 || curvatureDegrees >= 180.0)
        {
            throw new ArgumentOutOfRangeException(nameof(curvatureDegrees));
        }
        _maxSamples = maxSamples;
        _minSpacingPixels = minSpacingPixels;
        _maxIntervalMilliseconds = maxIntervalMilliseconds;
        _curvatureDegrees = curvatureDegrees;
    }

    internal int RawCount { get; private set; }
    internal int OverflowCount { get; private set; }
    internal int MaxSamples => _maxSamples;
    public int Count => _samples.Count;
    public Point this[int index] => _samples[index].Point;

    internal void Add(Point point) => Add(point, Environment.TickCount64);

    internal void Add(Point point, long timestampMilliseconds)
    {
        if (_samples.Count > 0 && timestampMilliseconds < _samples[^1].TimestampMilliseconds)
        {
            throw new ArgumentOutOfRangeException(nameof(timestampMilliseconds));
        }
        RawCount += 1;
        var sample = new TimedPoint(point, timestampMilliseconds);
        if (_samples.Count == 0)
        {
            _samples.Add(sample);
            return;
        }
        if (_samples.Count == 1)
        {
            if (_samples[0].Point != point || _samples[0].TimestampMilliseconds != timestampMilliseconds)
            {
                _samples.Add(sample);
            }
            return;
        }
        if (PreserveMiddle(_samples[^2], _samples[^1], sample))
        {
            _samples.Add(sample);
        }
        else
        {
            _samples[^1] = sample;
        }
        if (_samples.Count > _maxSamples)
        {
            OverflowCount += 1;
            RemoveLeastImportantInterior();
        }
    }

    internal void Clear()
    {
        _samples.Clear();
        RawCount = 0;
        OverflowCount = 0;
    }

    internal Point[] ToArray() => _samples.Select(sample => sample.Point).ToArray();

    public IEnumerator<Point> GetEnumerator() =>
        _samples.Select(sample => sample.Point).GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();

    private bool PreserveMiddle(TimedPoint first, TimedPoint middle, TimedPoint newest)
    {
        if (Distance(first.Point, middle.Point) < _minSpacingPixels
            && middle.TimestampMilliseconds - first.TimestampMilliseconds < _maxIntervalMilliseconds)
        {
            return false;
        }
        if (middle.TimestampMilliseconds - first.TimestampMilliseconds >= _maxIntervalMilliseconds)
        {
            return true;
        }
        if (TurnDegrees(first.Point, middle.Point, newest.Point) >= _curvatureDegrees)
        {
            return true;
        }
        return SelectionGeometry.PointSegmentDistance(middle.Point, first.Point, newest.Point)
            >= _minSpacingPixels;
    }

    private void RemoveLeastImportantInterior()
    {
        if (_samples.Count <= 2)
        {
            return;
        }
        var removeIndex = 1;
        var lowestImportance = double.MaxValue;
        for (var index = 1; index < _samples.Count - 1; index += 1)
        {
            var importance = Importance(index);
            if (importance < lowestImportance)
            {
                lowestImportance = importance;
                removeIndex = index;
            }
        }
        _samples.RemoveAt(removeIndex);
    }

    private double Importance(int index)
    {
        var previous = _samples[index - 1];
        var current = _samples[index];
        var following = _samples[index + 1];
        var spacingScore = SelectionGeometry.PointSegmentDistance(
            current.Point,
            previous.Point,
            following.Point) / _minSpacingPixels;
        var curvatureScore = TurnDegrees(
            previous.Point,
            current.Point,
            following.Point) / _curvatureDegrees;
        var intervalScore = (
            following.TimestampMilliseconds - previous.TimestampMilliseconds
        ) / (double)_maxIntervalMilliseconds;
        return Math.Max(spacingScore, Math.Max(curvatureScore, intervalScore));
    }

    private static double Distance(Point first, Point second) =>
        Math.Sqrt(
            (double)(second.X - first.X) * (second.X - first.X)
            + (double)(second.Y - first.Y) * (second.Y - first.Y));

    private static double TurnDegrees(Point first, Point middle, Point newest)
    {
        var incomingX = (double)middle.X - first.X;
        var incomingY = (double)middle.Y - first.Y;
        var outgoingX = (double)newest.X - middle.X;
        var outgoingY = (double)newest.Y - middle.Y;
        var incomingLength = Math.Sqrt(incomingX * incomingX + incomingY * incomingY);
        var outgoingLength = Math.Sqrt(outgoingX * outgoingX + outgoingY * outgoingY);
        if (incomingLength <= 1e-12 || outgoingLength <= 1e-12)
        {
            return 0.0;
        }
        var cosine = (
            incomingX * outgoingX + incomingY * outgoingY
        ) / (incomingLength * outgoingLength);
        return Math.Acos(Math.Clamp(cosine, -1.0, 1.0)) * 180.0 / Math.PI;
    }

    private readonly record struct TimedPoint(Point Point, long TimestampMilliseconds);
}
