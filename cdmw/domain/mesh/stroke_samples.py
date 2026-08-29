"""Bounded screen-space samples for long Mesh Editor gestures."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class StrokeSampleConfig:
    max_samples: int = 256
    min_spacing_pixels: float = 2.5
    max_interval_seconds: float = 0.050
    curvature_degrees: float = 12.0

    def __post_init__(self) -> None:
        if self.max_samples < 2:
            raise ValueError("stroke sample limit must be at least two")
        if not math.isfinite(self.min_spacing_pixels) or self.min_spacing_pixels <= 0.0:
            raise ValueError("stroke sample spacing must be positive and finite")
        if not math.isfinite(self.max_interval_seconds) or self.max_interval_seconds <= 0.0:
            raise ValueError("stroke sample interval must be positive and finite")
        if not math.isfinite(self.curvature_degrees) or not 0.0 < self.curvature_degrees < 180.0:
            raise ValueError("stroke curvature threshold must be between zero and 180 degrees")


@dataclass(frozen=True, slots=True)
class StrokeSample:
    x: float
    y: float
    timestamp_seconds: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.timestamp_seconds)):
            raise ValueError("stroke samples must contain finite values")


class StrokeSampleBuffer:
    """Incrementally simplify a pointer stream within a fixed memory bound.

    The first sample is immutable and the newest sample is always exact. A
    middle sample survives when it represents a turn, exceeds the screen-space
    deviation tolerance, or is needed to keep slow motion time-spaced. Once the
    hard limit is reached, the least important interior sample is removed.
    """

    def __init__(self, config: StrokeSampleConfig | None = None) -> None:
        self.config = config or StrokeSampleConfig()
        self._samples: list[StrokeSample] = []
        self._raw_count = 0
        self._overflow_count = 0

    @property
    def samples(self) -> tuple[StrokeSample, ...]:
        return tuple(self._samples)

    @property
    def points(self) -> tuple[tuple[float, float], ...]:
        return tuple((sample.x, sample.y) for sample in self._samples)

    @property
    def raw_count(self) -> int:
        return self._raw_count

    @property
    def retained_count(self) -> int:
        return len(self._samples)

    @property
    def dropped_count(self) -> int:
        return max(0, self._raw_count - len(self._samples))

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    def append(self, sample: StrokeSample) -> bool:
        """Add one raw sample and return whether the hard limit overflowed."""

        if not isinstance(sample, StrokeSample):
            raise TypeError("stroke buffer accepts StrokeSample values")
        if self._samples and sample.timestamp_seconds < self._samples[-1].timestamp_seconds:
            raise ValueError("stroke sample timestamps must be monotonic")
        self._raw_count += 1
        if not self._samples:
            self._samples.append(sample)
            return False
        if len(self._samples) == 1:
            if sample == self._samples[0]:
                return False
            self._samples.append(sample)
            return False
        if self._preserve_middle(self._samples[-2], self._samples[-1], sample):
            self._samples.append(sample)
        else:
            self._samples[-1] = sample
        overflowed = len(self._samples) > self.config.max_samples
        if overflowed:
            self._overflow_count += 1
            self._remove_least_important_interior()
        return overflowed

    def extend(self, samples: Iterable[StrokeSample]) -> bool:
        overflowed = False
        for sample in samples:
            overflowed = self.append(sample) or overflowed
        return overflowed

    def segments(self, max_samples: int | None = None) -> tuple[tuple[StrokeSample, ...], ...]:
        """Return bounded packets with one overlapping boundary sample."""

        limit = self.config.max_samples if max_samples is None else int(max_samples)
        if limit < 2:
            raise ValueError("stroke segment limit must be at least two")
        if not self._samples:
            return ()
        if len(self._samples) <= limit:
            return (tuple(self._samples),)
        result: list[tuple[StrokeSample, ...]] = []
        start = 0
        while start < len(self._samples) - 1:
            end = min(len(self._samples), start + limit)
            result.append(tuple(self._samples[start:end]))
            start = end - 1
        return tuple(result)

    def metrics(self) -> dict[str, int | float]:
        return {
            "raw_samples": self.raw_count,
            "retained_samples": self.retained_count,
            "dropped_samples": self.dropped_count,
            "overflow_count": self.overflow_count,
            "max_samples": self.config.max_samples,
            "min_spacing_pixels": self.config.min_spacing_pixels,
            "max_interval_ms": self.config.max_interval_seconds * 1000.0,
            "curvature_degrees": self.config.curvature_degrees,
        }

    def _preserve_middle(
        self,
        first: StrokeSample,
        middle: StrokeSample,
        newest: StrokeSample,
    ) -> bool:
        spacing = self.config.min_spacing_pixels
        if (
            _distance(first, middle) < spacing
            and middle.timestamp_seconds - first.timestamp_seconds < self.config.max_interval_seconds
        ):
            return False
        if middle.timestamp_seconds - first.timestamp_seconds >= self.config.max_interval_seconds:
            return True
        turn = _turn_degrees(first, middle, newest)
        if turn >= self.config.curvature_degrees:
            return True
        return _point_segment_distance(middle, first, newest) >= spacing

    def _remove_least_important_interior(self) -> None:
        if len(self._samples) <= 2:
            return
        remove_index = min(
            range(1, len(self._samples) - 1),
            key=self._importance,
        )
        del self._samples[remove_index]

    def _importance(self, index: int) -> tuple[float, int]:
        previous = self._samples[index - 1]
        current = self._samples[index]
        following = self._samples[index + 1]
        spacing_score = _point_segment_distance(
            current,
            previous,
            following,
        ) / self.config.min_spacing_pixels
        curvature_score = _turn_degrees(
            previous,
            current,
            following,
        ) / self.config.curvature_degrees
        interval_score = (
            following.timestamp_seconds - previous.timestamp_seconds
        ) / self.config.max_interval_seconds
        # The index tie-break removes the oldest equally unimportant sample,
        # preserving more recent detail around the current pointer.
        return max(spacing_score, curvature_score, interval_score), index


def _distance(first: StrokeSample, second: StrokeSample) -> float:
    return math.hypot(second.x - first.x, second.y - first.y)


def _point_segment_distance(
    point: StrokeSample,
    start: StrokeSample,
    end: StrokeSample,
) -> float:
    dx = end.x - start.x
    dy = end.y - start.y
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return _distance(point, start)
    projection = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_squared
    projection = max(0.0, min(1.0, projection))
    nearest_x = start.x + projection * dx
    nearest_y = start.y + projection * dy
    return math.hypot(point.x - nearest_x, point.y - nearest_y)


def _turn_degrees(
    first: StrokeSample,
    middle: StrokeSample,
    newest: StrokeSample,
) -> float:
    incoming_x = middle.x - first.x
    incoming_y = middle.y - first.y
    outgoing_x = newest.x - middle.x
    outgoing_y = newest.y - middle.y
    incoming_length = math.hypot(incoming_x, incoming_y)
    outgoing_length = math.hypot(outgoing_x, outgoing_y)
    if incoming_length <= 1e-12 or outgoing_length <= 1e-12:
        return 0.0
    cosine = (
        incoming_x * outgoing_x + incoming_y * outgoing_y
    ) / (incoming_length * outgoing_length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
