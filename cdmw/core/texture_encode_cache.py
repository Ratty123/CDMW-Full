"""Bounded, process-local reuse of validated native texture encodes."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

from cdmw.domain.cancellation import raise_if_cancelled


_MAX_BYTES = 128 * 1024 * 1024
_MAX_ENTRIES = 64
_CACHE: OrderedDict[tuple, tuple[bytes, dict]] = OrderedDict()
_LOCK = threading.Lock()


def encode_key(request, backend_identity, stop_event):
    """Paths and timestamps cannot identify edits or temporary prepared images."""
    digest = hashlib.sha256()
    with request.input_path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
            digest.update(block)
    raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
    return (backend_identity, digest.digest(), request.dds_format,
            request.width, request.height, request.mip_count,
            request.source_color_policy, request.mip_alpha_policy,
            request.alpha_coverage_reference, request.dds_alpha_mode)


def cached_encode(key):
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached[0], dict(cached[1])
    return None


def prepared_encode_bytes(output, stop_event):
    # Large results remain usable without making the cache grow without bound.
    if output.stat().st_size > _MAX_BYTES:
        return
    data = output.read_bytes()
    raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
    if len(data) > _MAX_BYTES:
        return
    return data


def remember_encode(key, data, report, stop_event):
    raise_if_cancelled(stop_event, "DirectXTex DDS encode cancelled.")
    with _LOCK:
        _CACHE.pop(key, None)
        while _CACHE and (len(_CACHE) >= _MAX_ENTRIES
                          or sum(len(value[0]) for value in _CACHE.values()) + len(data) > _MAX_BYTES):
            _CACHE.popitem(last=False)
        _CACHE[key] = data, dict(report)
