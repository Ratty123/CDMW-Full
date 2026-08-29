from __future__ import annotations

import math
import time

import pytest

from cdmw.domain.mesh import StrokeSample, StrokeSampleBuffer, StrokeSampleConfig


def _sample(index: int, x: float, y: float, *, interval: float = 0.001) -> StrokeSample:
    return StrokeSample(x=x, y=y, timestamp_seconds=index * interval)


def _distance_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return math.dist(point, start)
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    projection = max(0.0, min(1.0, projection))
    nearest = (start[0] + projection * dx, start[1] + projection * dy)
    return math.dist(point, nearest)


def _distance_to_path(point: tuple[float, float], path: tuple[tuple[float, float], ...]) -> float:
    return min(
        _distance_to_segment(point, path[index], path[index + 1])
        for index in range(len(path) - 1)
    )


def test_first_and_final_samples_remain_exact_after_2400_updates() -> None:
    buffer = StrokeSampleBuffer()
    raw = tuple(_sample(index, float(index), math.sin(index / 20.0) * 8.0) for index in range(2400))

    buffer.extend(raw)

    assert buffer.samples[0] == raw[0]
    assert buffer.samples[-1] == raw[-1]
    assert buffer.retained_count <= 256
    assert buffer.raw_count == 2400


def test_straight_high_rate_path_simplifies_strongly() -> None:
    buffer = StrokeSampleBuffer()

    buffer.extend(_sample(index, float(index), 20.0) for index in range(2400))

    assert buffer.retained_count < 60
    assert buffer.points[0] == (0.0, 20.0)
    assert buffer.points[-1] == (2399.0, 20.0)


def test_high_curvature_corners_are_retained() -> None:
    buffer = StrokeSampleBuffer(
        StrokeSampleConfig(max_samples=32, max_interval_seconds=1.0)
    )
    points = ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (40.0, 20.0))

    buffer.extend(
        StrokeSample(x, y, index * 0.01)
        for index, (x, y) in enumerate(points)
    )

    assert buffer.points == points


def test_slow_subpixel_motion_keeps_time_spaced_samples() -> None:
    buffer = StrokeSampleBuffer()

    buffer.extend(_sample(index, index * 0.1, 0.0, interval=0.010) for index in range(101))

    timestamps = tuple(sample.timestamp_seconds for sample in buffer.samples)
    assert len(timestamps) >= 17
    assert max(second - first for first, second in zip(timestamps, timestamps[1:])) <= 0.061


def test_smooth_curve_stays_within_screen_space_tolerance() -> None:
    buffer = StrokeSampleBuffer(
        StrokeSampleConfig(max_samples=256, max_interval_seconds=1.0)
    )
    raw_points = tuple(
        (index * 0.5, math.sin(index / 30.0) * 30.0)
        for index in range(1200)
    )

    buffer.extend(
        StrokeSample(x, y, index * 0.001)
        for index, (x, y) in enumerate(raw_points)
    )

    assert buffer.retained_count <= 256
    assert max(_distance_to_path(point, buffer.points) for point in raw_points) <= 2.6


def test_memory_and_final_append_cost_stay_bounded_after_limit() -> None:
    config = StrokeSampleConfig(max_samples=64, max_interval_seconds=1.0, curvature_degrees=1.0)
    buffer = StrokeSampleBuffer(config)
    buffer.extend(
        _sample(index, float(index), float(index % 2) * 10.0)
        for index in range(2400)
    )

    started = time.perf_counter()
    buffer.append(_sample(2400, 2400.0, 0.0))
    terminal_ms = (time.perf_counter() - started) * 1000.0

    assert buffer.retained_count == 64
    assert buffer.overflow_count > 0
    assert terminal_ms < 10.0


def test_segments_overlap_and_obey_packet_sample_limit() -> None:
    buffer = StrokeSampleBuffer(
        StrokeSampleConfig(max_samples=512, max_interval_seconds=1.0, curvature_degrees=1.0)
    )
    buffer.extend(
        _sample(index, float(index), float(index % 2) * 10.0)
        for index in range(400)
    )

    segments = buffer.segments(64)

    assert len(segments) > 1
    assert all(2 <= len(segment) <= 64 for segment in segments)
    assert all(first[-1] == second[0] for first, second in zip(segments, segments[1:]))
    assert segments[0][0] == buffer.samples[0]
    assert segments[-1][-1] == buffer.samples[-1]


@pytest.mark.parametrize(
    "config",
    (
        StrokeSampleConfig(max_samples=2),
        StrokeSampleConfig(min_spacing_pixels=1.0),
        StrokeSampleConfig(max_interval_seconds=0.001),
        StrokeSampleConfig(curvature_degrees=179.0),
    ),
)
def test_valid_config_boundaries_construct(config: StrokeSampleConfig) -> None:
    assert StrokeSampleBuffer(config).config == config
