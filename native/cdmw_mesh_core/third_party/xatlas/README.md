# xatlas

Vendored UV atlas generator used by `cdmw-mesh-core auto-uv-json`.

Source: https://github.com/jpcy/xatlas

The upstream MIT license notice is preserved in `xatlas.cpp`.

## Local modifications

**Reapply these after any update from upstream.** They are the only deviations
from the vendored source; everything else is upstream as copied.

`ArrayBase` and `BitImage` keep `size`, `capacity`, and `elementSize` as
`uint32_t`, so a product like `size * elementSize` is evaluated in 32 bits and
only then widened to the `size_t` that `memcpy`, `memmove`, `memset`, and
`XA_REALLOC_SIZE` take. One operand in each of those nine products is now cast
to `size_t` first, so the arithmetic happens in 64 bits:

| Line | Expression |
| --- | --- |
| 975 | `memcpy(buffer, data, (size_t)length * elementSize)` |
| 984 | `memcpy(other.buffer, buffer, (size_t)size * elementSize)` |
| 1004 | `memmove` offsets and length in `insertAt` |
| 1048 | `memcpy` destination offset and length in `push_back` |
| 1059 | `memmove` offsets and length in `removeAt` |
| 1112 | `XA_REALLOC_SIZE(..., (size_t)newCapacity * elementSize)` |
| 1213 | `memset(..., (size_t)m_base.size * m_base.elementSize)` |
| 1225 | `memset(..., (size_t)m_base.elementSize * m_base.size)` |
| 1370 | `memcpy` length in `BitImage::resize` |

Reaching the overflow needs more than 4 GB of element data in one array, which
no asset this tool opens comes close to, and the allocation and the copy use the
same truncated arithmetic so they would at least agree. The change is here
because CodeQL reports each one as `cpp/integer-multiplication-cast-to-long` at
high severity, and nine standing alerts in a security tab train people to ignore
the tab. Upstream has not been patched.
