# Tests

The `tests/` folder is regression coverage for implementation that lives under
`cdmw/` and `native/`. It is not application runtime code.

Most tests exercise behavior directly. Files named `*_source_guards.py` are
intentional wiring guards for large PySide UI surfaces where previous regressions
were caused by missing buttons, callbacks, or fallback paths. They are brittle by
nature, but they protect user-facing workflows until those surfaces have smaller
behavior-level harnesses.
