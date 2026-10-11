import io
import json
import hashlib

import pytest

from cdmw.core import streaming_json as streaming


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 64 * 1024])
def test_incremental_json_matches_standard_decoder_across_boundaries(monkeypatch, chunk_size):
    monkeypatch.setattr(streaming, "JSON_IO_CHUNK", chunk_size)
    value = {"unicode": "å😀\udc00", "escapes": '\\"\n\t\r\b\f/',
             "empty": [{}, [], ""], "values": [None, True, False, -1, 1.25e-40, 1.6e32]}
    encoded = json.dumps(value)
    assert streaming.read_json(io.StringIO(encoded)) == value
    destination = io.StringIO()
    streaming.write_json(destination, value)
    assert json.loads(destination.getvalue()) == value


@pytest.mark.parametrize("source", ['{"x":1,}', '[1,]', '{"x" 1}', '[1 2]', 'true false',
                                    '"unterminated', '"\\q"', '"\\uQQQQ"', '"\\ud８００"', '01', '1e', '', '"x\ny"'])
def test_incremental_json_rejects_malformed_documents(source):
    with pytest.raises(ValueError):
        streaming.read_json(io.StringIO(source))


def test_lazy_arrays_preserve_canonical_bytes_and_fingerprints():
    expected = {"values": [{"a": (), "b": (1.5, 2)}]}
    value = {"values": streaming.JsonArray(lambda: iter([
        {"a": streaming.JsonArray(lambda: iter(())), "b": (1.5, 2)}]))}
    stream = io.StringIO()
    streaming.write_json(stream, value)
    encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    assert stream.getvalue() == encoded
    assert streaming.json_sha256(value) == hashlib.sha256(encoded.encode()).hexdigest()


def test_stream_writer_checks_cancellation_between_chunks(monkeypatch):
    monkeypatch.setattr(streaming, "JSON_IO_CHUNK", 16)
    calls = []

    def cancelled():
        calls.append(True)
        if len(calls) == 2:
            raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        streaming.write_json(io.StringIO(), list(range(100)), check_cancelled=cancelled)
    assert len(calls) == 2
