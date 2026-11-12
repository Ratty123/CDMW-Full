"""ChaCha20 for encrypted archive entries, without the ``cryptography`` package.

The archives use RFC 7539 ChaCha20 with a 16-byte "nonce" laid out the way
OpenSSL and ``cryptography`` take it: a 32-bit little-endian block counter
followed by the 96-bit nonce. Encryption and decryption are the same XOR.

Two paths produce the keystream:

- ``openssl``: the ``libcrypto`` that Python's own ``_ssl`` module loads, called
  through ``ctypes``. It is the same OpenSSL code ``cryptography`` wraps, at the
  same speed, and it adds no file to the package.
- ``numpy``: an implementation written here, vectorised over blocks. It is the
  independent reference the tests compare against, and the fallback when the
  OpenSSL library cannot be loaded. It is far slower on large payloads.

Both refuse, as ``cryptography`` does, a payload whose last block would carry
the 32-bit counter past ``0xFFFFFFFF``. (OpenSSL itself would carry into the
next nonce word; the archive's native reader matches the refusal, so the check
is made here before either path runs.)
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path

import numpy as np

KEY_SIZE = 32
NONCE_SIZE = 16
BLOCK_SIZE = 64
COUNTER_OVERFLOW_MESSAGE = (
    "Exceeded the maximum number of bytes that can be encrypted with ChaCha20 for this nonce. "
    "The 32-bit counter portion of the nonce would overflow."
)

_SIGMA = np.frombuffer(b"expand 32-byte k", dtype="<u4")
# Blocks per numpy pass: 16 Ki blocks is 1 MiB of keystream and about 2 MiB of
# working arrays, small enough to stay in cache-friendly sizes.
_NUMPY_BLOCKS_PER_PASS = 16 * 1024
# EVP_EncryptUpdate takes an int length.
_OPENSSL_MAX_UPDATE = 1 << 30


def _check(data_length: int, key: bytes, nonce: bytes) -> int:
    if len(key) != KEY_SIZE:
        raise ValueError(f"ChaCha20 key must be {KEY_SIZE} bytes, not {len(key)}.")
    if len(nonce) != NONCE_SIZE:
        raise ValueError(f"ChaCha20 nonce must be {NONCE_SIZE} bytes, not {len(nonce)}.")
    counter = int.from_bytes(nonce[:4], "little")
    blocks = -(-data_length // BLOCK_SIZE)
    if counter + blocks > 1 << 32:
        raise ValueError(COUNTER_OVERFLOW_MESSAGE)
    return counter


# ---- numpy -----------------------------------------------------------------------------


def _rotl(value: np.ndarray, shift: int, scratch: np.ndarray) -> None:
    np.right_shift(value, 32 - shift, out=scratch)
    np.left_shift(value, shift, out=value)
    np.bitwise_or(value, scratch, out=value)


def _quarter_round(x: np.ndarray, a: int, b: int, c: int, d: int, scratch: np.ndarray) -> None:
    np.add(x[a], x[b], out=x[a])
    np.bitwise_xor(x[d], x[a], out=x[d])
    _rotl(x[d], 16, scratch)
    np.add(x[c], x[d], out=x[c])
    np.bitwise_xor(x[b], x[c], out=x[b])
    _rotl(x[b], 12, scratch)
    np.add(x[a], x[b], out=x[a])
    np.bitwise_xor(x[d], x[a], out=x[d])
    _rotl(x[d], 8, scratch)
    np.add(x[c], x[d], out=x[c])
    np.bitwise_xor(x[b], x[c], out=x[b])
    _rotl(x[b], 7, scratch)


def _numpy_keystream(key_words: np.ndarray, nonce_words: np.ndarray, first_counter: int, blocks: int) -> bytes:
    state = np.empty((16, blocks), dtype=np.uint32)
    state[0:4] = _SIGMA[:, None]
    state[4:12] = key_words[:, None]
    state[12] = np.arange(first_counter, first_counter + blocks, dtype=np.uint64).astype(np.uint32)
    state[13:16] = nonce_words[:, None]
    x = state.copy()
    scratch = np.empty(blocks, dtype=np.uint32)
    for _ in range(10):
        _quarter_round(x, 0, 4, 8, 12, scratch)
        _quarter_round(x, 1, 5, 9, 13, scratch)
        _quarter_round(x, 2, 6, 10, 14, scratch)
        _quarter_round(x, 3, 7, 11, 15, scratch)
        _quarter_round(x, 0, 5, 10, 15, scratch)
        _quarter_round(x, 1, 6, 11, 12, scratch)
        _quarter_round(x, 2, 7, 8, 13, scratch)
        _quarter_round(x, 3, 4, 9, 14, scratch)
    np.add(x, state, out=x)
    return np.ascontiguousarray(x.T).astype("<u4", copy=False).tobytes()


def _numpy_xor(data: bytes, key: bytes, nonce: bytes, counter: int) -> bytes:
    key_words = np.frombuffer(key, dtype="<u4").astype(np.uint32)
    nonce_words = np.frombuffer(nonce[4:], dtype="<u4").astype(np.uint32)
    source = np.frombuffer(data, dtype=np.uint8)
    out = np.empty(len(data), dtype=np.uint8)
    step = _NUMPY_BLOCKS_PER_PASS * BLOCK_SIZE
    for start in range(0, len(data), step):
        end = min(len(data), start + step)
        blocks = -(-(end - start) // BLOCK_SIZE)
        keystream = np.frombuffer(
            _numpy_keystream(key_words, nonce_words, counter + start // BLOCK_SIZE, blocks), dtype=np.uint8
        )
        np.bitwise_xor(source[start:end], keystream[: end - start], out=out[start:end])
    return out.tobytes()


# ---- OpenSSL through ctypes -------------------------------------------------------------


class _OpenSsl:
    def __init__(self, library: ctypes.CDLL) -> None:
        self.new = library.EVP_CIPHER_CTX_new
        self.new.restype = ctypes.c_void_p
        self.new.argtypes = ()
        self.free = library.EVP_CIPHER_CTX_free
        self.free.restype = None
        self.free.argtypes = (ctypes.c_void_p,)
        self.cipher = library.EVP_chacha20
        self.cipher.restype = ctypes.c_void_p
        self.cipher.argtypes = ()
        self.init = library.EVP_EncryptInit_ex
        self.init.restype = ctypes.c_int
        self.init.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)
        self.update = library.EVP_EncryptUpdate
        self.update.restype = ctypes.c_int
        self.update.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_void_p,
            ctypes.c_int,
        )
        if not self.cipher():
            raise OSError("libcrypto has no ChaCha20 cipher")

    def xor(self, data: bytes, key: bytes, nonce: bytes) -> bytes:
        size = len(data)
        out = bytearray(size)
        if size == 0:
            return bytes(out)
        context = self.new()
        if not context:
            raise MemoryError("EVP_CIPHER_CTX_new failed")
        try:
            if self.init(context, self.cipher(), None, key, nonce) != 1:
                raise ValueError("OpenSSL refused the ChaCha20 key or nonce.")
            out_buffer = (ctypes.c_char * size).from_buffer(out)
            source = ctypes.c_char_p(data)
            written = ctypes.c_int(0)
            base_out = ctypes.addressof(out_buffer)
            base_in = ctypes.cast(source, ctypes.c_void_p).value
            for start in range(0, size, _OPENSSL_MAX_UPDATE):
                length = min(_OPENSSL_MAX_UPDATE, size - start)
                if self.update(context, base_out + start, ctypes.byref(written), base_in + start, length) != 1:
                    raise ValueError("OpenSSL ChaCha20 update failed.")
                if written.value != length:
                    raise ValueError("OpenSSL ChaCha20 returned a short block.")
            del out_buffer
        finally:
            self.free(context)
        return bytes(out)


def _libcrypto_candidates() -> list[str]:
    names: list[str] = []
    directories: list[Path] = []
    try:
        import _ssl  # noqa: F401 - loads Python's own libcrypto into the process

        ssl_file = getattr(_ssl, "__file__", None)
        if ssl_file:
            directories.append(Path(ssl_file).resolve().parent)
    except ImportError:
        pass
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        directories.append(Path(frozen_root))
    directories.append(Path(sys.base_prefix) / "DLLs")
    directories.append(Path(sys.base_prefix))
    for directory in directories:
        try:
            names.extend(str(path) for path in sorted(directory.glob("libcrypto-3*.dll")))
        except OSError:
            continue
    # Already loaded by _ssl: the loader returns the same module by its name.
    names.extend(("libcrypto-3-x64", "libcrypto-3"))
    return list(dict.fromkeys(names))


_openssl_lock = threading.Lock()
_openssl: _OpenSsl | None = None
_openssl_failure = ""
_openssl_tried = False


def _load_openssl() -> _OpenSsl | None:
    global _openssl, _openssl_failure, _openssl_tried
    with _openssl_lock:
        if _openssl_tried:
            return _openssl
        _openssl_tried = True
        if os.environ.get("CDMW_CHACHA20_BACKEND", "").strip().casefold() == "numpy":
            _openssl_failure = "CDMW_CHACHA20_BACKEND=numpy"
            return None
        failures = []
        for name in _libcrypto_candidates():
            try:
                _openssl = _OpenSsl(ctypes.CDLL(name))
                return _openssl
            except (OSError, AttributeError) as exc:
                failures.append(f"{name}: {exc}")
        _openssl_failure = "; ".join(failures) or "no libcrypto found"
        return None


def chacha20_backend() -> str:
    """``openssl`` or ``numpy``: which path ``chacha20_xor`` uses in this process."""

    return "openssl" if _load_openssl() is not None else "numpy"


def chacha20_xor(data: bytes, key: bytes, nonce: bytes, *, backend: str | None = None) -> bytes:
    """XOR ``data`` with the ChaCha20 keystream for ``key`` and the 16-byte ``nonce``.

    ``backend`` forces ``openssl`` or ``numpy`` (tests and the comparison script);
    the default uses OpenSSL when it loads and numpy otherwise.
    """

    data = bytes(data)
    key = bytes(key)
    nonce = bytes(nonce)
    counter = _check(len(data), key, nonce)
    if backend not in (None, "openssl", "numpy"):
        raise ValueError(f"Unknown ChaCha20 backend {backend!r}.")
    if backend != "numpy":
        library = _load_openssl()
        if library is not None:
            return library.xor(data, key, nonce)
        if backend == "openssl":
            raise OSError(f"OpenSSL ChaCha20 is unavailable: {_openssl_failure}")
    return _numpy_xor(data, key, nonce, counter)
